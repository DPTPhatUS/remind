import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  LiveView,
  SessionStatus,
  VisionMessage,
  VoiceStatus,
} from "@/lib/api-types";
import { captureFrames } from "./capture";
import { recordClips } from "./audio";
import { acceptResult } from "./protocol";
import { useConversationJobs } from "./jobs";
import { pauseStaleView } from "./state";

type ClipRecorder = ReturnType<typeof recordClips>;
type SessionState = "idle" | "starting" | "live" | "saving";
type VisionResponse = VisionMessage | { type: "error"; message: string };

type Resources = {
  stream?: MediaStream;
  socket?: WebSocket;
  generation?: string;
  stopFrames?: () => void;
  clips?: ClipRecorder;
};
export function useLiveSession() {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<SessionState>("idle");
  const [error, setError] = useState("");
  const [memoryStatus, setMemoryStatus] = useState("");
  const [voiceReady, setVoiceReady] = useState<boolean | null>(null);
  const [uploadPaused, setUploadPaused] = useState(false);
  const retainedClips = useRef<ClipRecorder | null>(null);
  const [view, setView] = useState<LiveView | null>(null);
  const [diagnostics, setDiagnostics] = useState({
    fps: 0,
    latency: 0,
    processing: 0,
    dropped: 0,
  });
  const resources = useRef<Resources>({});
  const epoch = useRef(0);
  const lastResult = useRef(0);
  const stop = useCallback(async () => {
    const token = ++epoch.current;
    const current = resources.current;
    resources.current = {};
    if (!current.generation) {
      setStatus("idle");
      return;
    }
    setStatus("saving");
    current.stopFrames?.();
    const flushing = current.clips?.stop();
    current.stream?.getTracks().forEach((track) => track.stop());
    current.socket?.close();
    if (video.current) video.current.srcObject = null;
    setView(null);
    try {
      await flushing;
      if (current.generation)
        await api(`/session/${current.generation}/stop`, { method: "POST" });
    } catch (e) {
      if (token === epoch.current) setError(String(e));
    }
    if (token === epoch.current) setStatus("idle");
  }, []);
  const start = useCallback(async () => {
    if (uploadPaused) {
      setError(
        "Download or retry the retained conversation before starting another session.",
      );
      return;
    }
    const token = ++epoch.current;
    retainedClips.current = null;
    setStatus("starting");
    setError("");
    setMemoryStatus("");
    try {
      const session = await api<SessionStatus>("/session", { method: "POST" });
      if (token !== epoch.current) {
        await api(`/session/${session.generation}/stop`, { method: "POST" });
        return;
      }
      resources.current.generation = session.generation;
      setVoiceReady(session.voice_ready);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30 },
        },
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      if (token !== epoch.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      resources.current.stream = stream;
      const preview = video.current;
      if (!preview) throw new Error("Camera view unavailable");
      preview.srcObject = stream;
      await preview.play();
      if (token !== epoch.current) return;
      const url = new URL(
        `/api/live/${session.generation}/vision`,
        location.href,
      );
      url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(url);
      resources.current.socket = socket;
      let lastSequence = -1;
      socket.onmessage = (event) => {
        if (token !== epoch.current) return;
        const message = JSON.parse(event.data) as VisionResponse;
        if (message.type !== "vision") {
          setError(message.message ?? "Vision error");
          return;
        }
        const now = performance.now();
        if (!acceptResult(message, session.generation, lastSequence, now))
          return;
        lastSequence = message.sequence;
        lastResult.current = now;
        setView(message);
        setDiagnostics({
          fps: message.processed_fps,
          latency: now - message.capture_ms,
          processing: message.processing_ms,
          dropped: message.dropped,
        });
      };
      socket.onopen = () => {
        if (token !== epoch.current) {
          socket.close();
          return;
        }
        try {
          resources.current.stopFrames = captureFrames(
            preview,
            socket,
            session.generation,
          );
          if (session.memory_available) {
            const clips: ClipRecorder = recordClips(
              stream,
              session.generation,
              (message) => {
                if (retainedClips.current === clips) setMemoryStatus(message);
              },
              (paused) => {
                if (retainedClips.current === clips) setUploadPaused(paused);
              },
            );
            retainedClips.current = clips;
            resources.current.clips = clips;
          } else {
            setMemoryStatus(
              "Conversation memory is off. Configure the OpenAI API key to enable it.",
            );
          }
          setStatus("live");
        } catch (e) {
          setError(String(e));
          void stop();
        }
      };
      socket.onclose = () => {
        if (token === epoch.current) {
          setError("Connection lost. Start again to resume.");
          void stop();
        }
      };
    } catch (e) {
      if (token === epoch.current) {
        setError(e instanceof Error ? e.message : String(e));
        await stop();
      }
    }
  }, [video, stop, uploadPaused]);
  useEffect(() => {
    let active = true;
    void api<VoiceStatus>("/user/voice")
      .then((voice) => {
        if (active) setVoiceReady(voice.ready);
      })
      .catch(() => {
        if (active) {
          setMemoryStatus(
            "Voice setup status is unavailable. Check the server connection.",
          );
        }
      });
    return () => { active = false; };
  }, []);
  const jobsStatus = useConversationJobs();
  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = performance.now();
      if (now - lastResult.current > 500) {
        setView((current) => pauseStaleView(current, now));
      }
    }, 250);
    return () => {
      clearInterval(timer);
      void stop();
    };
  }, [stop]);
  const attachVideo = useCallback((node: HTMLVideoElement | null) => {
    video.current = node;
  }, []);
  const retryUpload = () => retainedClips.current?.retry();
  const downloadClip = () => retainedClips.current?.download();
  return {
    attachVideo,
    status,
    error,
    memoryStatus,
    voiceReady,
    jobsStatus,
    uploadPaused,
    retryUpload,
    downloadClip,
    view,
    diagnostics,
    start,
    stop,
  };
}
