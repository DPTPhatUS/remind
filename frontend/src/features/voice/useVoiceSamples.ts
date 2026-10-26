import { useEffect, useRef, useState } from "react";

export const VOICE_SAMPLE_COUNT = 3;
export const VOICE_SAMPLE_SECONDS = 8;

type VoiceSample = { audio: Blob; url: string };
type RecordingResources = {
  generation: number;
  recorder: MediaRecorder | null;
  stream: MediaStream | null;
  timer: ReturnType<typeof setInterval> | null;
  samples: (VoiceSample | null)[];
};

function releaseMicrophone(resources: RecordingResources) {
  if (resources.timer !== null) clearInterval(resources.timer);
  resources.timer = null;
  if (resources.recorder?.state === "recording") resources.recorder.stop();
  resources.recorder = null;
  resources.stream?.getTracks().forEach((track) => track.stop());
  resources.stream = null;
}

export function useVoiceSamples() {
  const resources = useRef<RecordingResources>({
    generation: 0,
    recorder: null,
    stream: null,
    timer: null,
    samples: Array.from({ length: VOICE_SAMPLE_COUNT }, () => null),
  });
  const [samples, setSamples] = useState<(VoiceSample | null)[]>(() =>
    Array.from({ length: VOICE_SAMPLE_COUNT }, () => null),
  );
  const [recording, setRecording] = useState<number | null>(null);
  const [waitingForMicrophone, setWaitingForMicrophone] = useState(false);
  const [seconds, setSeconds] = useState(VOICE_SAMPLE_SECONDS);
  const [error, setError] = useState("");

  useEffect(() => {
    const current = resources.current;
    return () => {
      current.generation++;
      releaseMicrophone(current);
      current.samples.forEach((sample) => {
        if (sample) URL.revokeObjectURL(sample.url);
      });
      current.samples = current.samples.map(() => null);
    };
  }, []);

  async function record(index: number) {
    const current = resources.current;
    const generation = ++current.generation;
    setError("");
    setRecording(index);
    setWaitingForMicrophone(true);
    setSeconds(VOICE_SAMPLE_SECONDS);
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === "undefined"
      ) {
        throw new Error(
          "Microphone recording is unavailable. Open Remind on localhost or HTTPS in a recent browser.",
        );
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      if (generation !== current.generation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      current.stream = stream;
      const mimeType = [
        "audio/webm;codecs=opus", "audio/webm", "audio/mp4",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      if (!mimeType) {
        throw new Error(
          "This browser cannot record audio. Try a recent Chrome or Firefox browser.",
        );
      }

      const recorder = new MediaRecorder(stream, { mimeType });
      current.recorder = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => {
        if (generation !== current.generation) return;
        current.generation++;
        releaseMicrophone(current);
        setRecording(null);
        setError("The recording failed. Please try that sample again.");
      };
      recorder.onstop = () => {
        if (generation !== current.generation) return;
        releaseMicrophone(current);
        setRecording(null);
        const audio = new Blob(chunks, { type: mimeType });
        if (!audio.size) {
          setError(
            "No audio was captured. Check the microphone and try again.",
          );
          return;
        }
        const oldSample = current.samples[index];
        if (oldSample) URL.revokeObjectURL(oldSample.url);
        const sample = { audio, url: URL.createObjectURL(audio) };
        current.samples = current.samples.map((previous, i) =>
          i === index ? sample : previous,
        );
        setSamples(current.samples);
      };
      recorder.start();
      setWaitingForMicrophone(false);
      let remaining = VOICE_SAMPLE_SECONDS;
      current.timer = setInterval(() => {
        setSeconds(--remaining);
        if (remaining <= 0 && recorder.state === "recording") recorder.stop();
      }, 1000);
    } catch (error) {
      if (generation !== current.generation) return;
      releaseMicrophone(current);
      setRecording(null);
      setWaitingForMicrophone(false);
      setError(error instanceof Error ? error.message : String(error));
    }
  }

  function cancel() {
    resources.current.generation++;
    releaseMicrophone(resources.current);
    setRecording(null);
    setWaitingForMicrophone(false);
  }

  function clear() {
    const current = resources.current;
    current.samples.forEach((sample) => {
      if (sample) URL.revokeObjectURL(sample.url);
    });
    current.samples = current.samples.map(() => null);
    setSamples(current.samples);
    setError("");
  }

  return {
    samples, recording, waitingForMicrophone, seconds, error,
    record, cancel, clear,
  };
}
