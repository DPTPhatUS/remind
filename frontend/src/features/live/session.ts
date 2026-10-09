import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { FaceTrack, VisionMessage } from "@/lib/api-types";
import { captureFrames } from "./capture";
import { recordClips } from "./audio";
import { acceptResult } from "./protocol";

type Resources = {
  stream?: MediaStream;
  socket?: WebSocket;
  generation?: string;
  stopFrames?: () => void;
  clips?: ReturnType<typeof recordClips>;
};
export function useLiveSession() {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [memoryStatus, setMemoryStatus] = useState("");
  const [uploadPaused, setUploadPaused] = useState(false);
  const retainedClips = useRef<ReturnType<typeof recordClips> | null>(null);
  const [jobsStatus, setJobsStatus] = useState("");
  const [tracks, setTracks] = useState<FaceTrack[]>([]);
  const [diagnostics, setDiagnostics] = useState({
    fps: 0,
    latency: 0,
    processing: 0,
    dropped: 0,
  });
  const resources = useRef<Resources>({});
  const trace = useRef<Record<string, unknown>[]>([]);
  const epoch = useRef(0),
    lastResult = useRef(0);
  const stop = useCallback(async () => {
    epoch.current++;
    const current = resources.current;
    resources.current = {};
    setStatus("saving");
    current.stopFrames?.();
    const flushing = current.clips?.stop();
    current.stream?.getTracks().forEach((track) => track.stop());
    current.socket?.close();
    setTracks([]);
    try {
      await flushing;
      if (current.generation)
        await api(`/session/${current.generation}/stop`, { method: "POST" });
    } catch (e) {
      setError(String(e));
    }
    setStatus("idle");
  }, []);
  const start = useCallback(async () => {
    const token = ++epoch.current;
    if (uploadPaused) {
      setError(
        "Download or retry the retained conversation before starting another session.",
      );
      return;
    }
    trace.current = [];
    setStatus("starting");
    setError("");
    setMemoryStatus("");
    try {
      const session = await api<{
        generation: string;
        memory_available: boolean;
      }>("/session", { method: "POST" });
      if (token !== epoch.current) {
        await api(`/session/${session.generation}/stop`, { method: "POST" });
        return;
      }
      resources.current.generation = session.generation;
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
      if (!video.current) throw new Error("Camera view unavailable");
      video.current.srcObject = stream;
      await video.current.play();
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
        const message = JSON.parse(event.data) as VisionMessage & {
          message?: string;
        };
        if (message.type !== "vision") {
          setError(message.message ?? "Vision error");
          return;
        }
        const now = performance.now();
        if (!acceptResult(message, session.generation, lastSequence, now))
          return;
        lastSequence = message.sequence;
        lastResult.current = now;
        const entry: Record<string, unknown> = {
          generation: session.generation,
          sequence: message.sequence,
          capture_ms: message.capture_ms,
          received_ms: now,
          processing_ms: message.processing_ms,
          clock: "browser-performance",
          faces: message.tracks.length,
          dropped: message.dropped,
        };
        if (trace.current.length < 100000) trace.current.push(entry);
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            if (token === epoch.current) entry.painted_ms = performance.now();
          }),
        );
        setTracks(message.tracks);
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
            video.current!,
            socket,
            session.generation,
          );
          if (session.memory_available)
            retainedClips.current = resources.current.clips = recordClips(
              stream,
              session.generation,
              setMemoryStatus,
              setUploadPaused,
            );
          else
            setMemoryStatus(
              "Conversation memory is off. Configure the OpenAI API key to enable it.",
            );
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
    const poll = window.setInterval(() => {
      void api<{ status: string }[]>("/jobs")
        .then((jobs) => {
          const failed = jobs.filter((j) => j.status === "failed").length;
          setJobsStatus(
            failed
              ? `${failed} conversation clip(s) could not be processed. Check your connection or service setup, then retry.`
              : jobs.length
                ? `${jobs.length} conversation clip(s) processing.`
                : "",
          );
        })
        .catch(() => {});
    }, 3000);
    const timer = window.setInterval(() => {
      if (performance.now() - lastResult.current > 500)
        setTracks((current) => (current.length ? [] : current));
    }, 250);
    return () => {
      clearInterval(poll);
      clearInterval(timer);
      void stop();
    };
  }, [stop]);
  const attachVideo = useCallback((node: HTMLVideoElement | null) => {
    video.current = node;
  }, []);
  const retryUpload = () => retainedClips.current?.retry();
  const downloadClip = () => {
    retainedClips.current?.download();
    setUploadPaused(false);
  };
  const retryJobs = async () => {
    try {
      const jobs = await api<{ id: string; status: string }[]>("/jobs");
      for (const job of jobs.filter((j) => j.status === "failed"))
        await api(`/jobs/${job.id}/retry`, { method: "POST" });
      setJobsStatus("Retrying failed conversations.");
    } catch (error) {
      setError(String(error));
    }
  };
  const exportTrace = () => {
    const data = {
      schema: 1,
      model_backend: "real",
      browser: navigator.userAgent,
      timing_note:
        "painted_ms is a two-animation-frame upper bound after result receipt",
      frames: trace.current,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "remind-performance.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return {
    attachVideo,
    status,
    error,
    memoryStatus,
    jobsStatus,
    uploadPaused,
    retryUpload,
    downloadClip,
    exportTrace,
    retryJobs,
    tracks,
    diagnostics,
    start,
    stop,
  };
}
