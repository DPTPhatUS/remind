import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { VoiceStatus } from "@/lib/api-types";

type Sample = { audio: Blob; url: string };
const SAMPLE_COUNT = 3;
const SAMPLE_SECONDS = 8;
const prompts = [
  "Talk about your morning and the things you enjoy doing.",
  "Describe a familiar place or a happy memory.",
  "Tell us about your usual day, in your own words.",
];

async function audioBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () =>
      reject(new Error("Could not read the voice recording."));
    reader.readAsDataURL(blob);
  });
}

export function SetupPage() {
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [samples, setSamples] = useState<(Sample | null)[]>([null, null, null]);
  const [recording, setRecording] = useState<number | null>(null);
  const [seconds, setSeconds] = useState(SAMPLE_SECONDS);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const referenceSaved = Boolean(voice?.reference_saved || voice?.ready);
  const generation = useRef(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const urls = useRef(new Set<string>());
  const stopMedia = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    if (recorder.current?.state === "recording") recorder.current.stop();
    recorder.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  };
  useEffect(() => {
    const token = ++generation.current;
    api<VoiceStatus>("/user/voice")
      .then((data) => {
        if (token === generation.current) setVoice(data);
      })
      .catch((e) => {
        if (token === generation.current) setError(String(e));
      })
      .finally(() => {
        if (token === generation.current) setLoading(false);
      });
    const currentUrls = urls.current;
    const lifecycle = generation;
    return () => {
      lifecycle.current++;
      stopMedia();
      currentUrls.forEach((url) => URL.revokeObjectURL(url));
      currentUrls.clear();
    };
  }, []);

  async function record(index: number) {
    const token = ++generation.current;
    setError("");
    setNotice("");
    setRecording(index);
    setSeconds(SAMPLE_SECONDS);
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      if (token !== generation.current) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = media;
      const mimeType = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      if (!mimeType)
        throw new Error(
          "This browser cannot record audio. Try a recent Chrome or Firefox browser.",
        );
      const current = new MediaRecorder(media, { mimeType });
      recorder.current = current;
      const chunks: Blob[] = [];
      current.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      current.onerror = () => {
        if (token !== generation.current) return;
        generation.current++;
        stopMedia();
        setRecording(null);
        setError("The recording failed. Please try that sample again.");
      };
      current.onstop = () => {
        if (token !== generation.current) return;
        stopMedia();
        setRecording(null);
        const audio = new Blob(chunks, { type: mimeType });
        if (!audio.size) {
          setError(
            "No audio was captured. Check the microphone and try again.",
          );
          return;
        }
        const url = URL.createObjectURL(audio);
        urls.current.add(url);
        setSamples((previous) => {
          const old = previous[index];
          if (old) {
            URL.revokeObjectURL(old.url);
            urls.current.delete(old.url);
          }
          return previous.map((sample, i) =>
            i === index ? { audio, url } : sample,
          );
        });
      };
      current.start();
      let remaining = SAMPLE_SECONDS;
      timer.current = setInterval(() => {
        remaining--;
        setSeconds(remaining);
        if (remaining <= 0 && current.state === "recording") current.stop();
      }, 1000);
    } catch (e) {
      if (token !== generation.current) return;
      stopMedia();
      setRecording(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function cancel() {
    generation.current++;
    stopMedia();
    setRecording(null);
    setNotice("Recording cancelled. You can try again when ready.");
  }

  async function submit() {
    const token = ++generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const encoded = await Promise.all(
        samples.map((sample) => audioBase64(sample!.audio)),
      );
      const status = await api<VoiceStatus>("/user/voice", {
        method: "POST",
        body: JSON.stringify({ samples: encoded }),
      });
      if (token !== generation.current) return;
      setVoice(status);
      urls.current.forEach((url) => URL.revokeObjectURL(url));
      urls.current.clear();
      setSamples([null, null, null]);
      setNotice(
        "Voice setup saved. Remind can now learn about visitors automatically.",
      );
    } catch (e) {
      if (token === generation.current) setError(String(e));
    } finally {
      if (token === generation.current) setBusy(false);
    }
  }

  async function remove() {
    if (
      !confirm(
        "Remove the user’s saved voice? Automatic profile learning will pause until a new voice is saved.",
      )
    )
      return;
    const token = ++generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const status = await api<VoiceStatus>("/user/voice", {
        method: "DELETE",
      });
      if (token !== generation.current) return;
      setVoice(status);
      setNotice(
        "Saved voice removed. Conversation summaries are still available.",
      );
    } catch (e) {
      if (token === generation.current) setError(String(e));
    } finally {
      if (token === generation.current) setBusy(false);
    }
  }

  return (
    <main className="content setup-page">
      <div className="page-heading">
        <p className="eyebrow">For a helper or caregiver</p>
        <h1>Set up the user’s voice</h1>
        <p>
          Help Remind recognize when the user is speaking, so it can learn about
          the person in front automatically.
        </p>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="success">
          {notice}
        </p>
      )}
      <section className="setup-status" aria-label="Saved voice status">
        <span className={`status-dot ${voice?.ready ? "active" : ""}`} />
        <div>
          <strong>
            {loading
              ? "Checking saved voice…"
              : voice?.ready
                ? "User’s voice is ready"
                : referenceSaved
                  ? "Saved voice is temporarily unavailable"
                  : "User’s voice has not been set up"}
          </strong>
          <p>
            {referenceSaved && voice
              ? `${voice.sample_count} samples saved${voice.updated_at ? ` · ${new Date(voice.updated_at).toLocaleDateString()}` : ""}. Record three new samples below to replace them.`
              : "Face recognition and conversation summaries work without a saved voice. Learning personal facts starts after setup."}
          </p>
        </div>
      </section>
      {voice?.model_available === false && (
        <p role="status" className="muted">
          Voice recognition is unavailable. Ask the installer to check the local
          voice models and dependencies. Any saved voice reference is retained.
        </p>
      )}
      <section aria-labelledby="recording-guide">
        <h2 id="recording-guide">Three short recordings</h2>
        <p>
          Choose a quiet place. Only the user should speak during each
          eight-second recording. They can use the suggestions below or speak
          naturally in English.
        </p>
        <div className="voice-samples">
          {prompts.map((prompt, index) => (
            <article className="voice-sample" key={prompt}>
              <div className="sample-heading">
                <h3>Sample {index + 1}</h3>
                <span>{samples[index] ? "Recorded" : "Not recorded"}</span>
              </div>
              <p>{prompt}</p>
              {samples[index] && (
                <audio
                  controls
                  src={samples[index].url}
                  aria-label={`Play sample ${index + 1}`}
                />
              )}
              {recording === index ? (
                <div>
                  <p role="status" className="recording-status">
                    Recording… {seconds} seconds left
                  </p>
                  <button className="secondary" onClick={cancel}>
                    Cancel recording
                  </button>
                </div>
              ) : (
                <button
                  className="secondary"
                  disabled={
                    recording !== null ||
                    busy ||
                    loading ||
                    voice?.model_available === false
                  }
                  onClick={() => void record(index)}
                >
                  {samples[index]
                    ? `Retake sample ${index + 1}`
                    : `Record sample ${index + 1}`}
                </button>
              )}
            </article>
          ))}
        </div>
        <div className="setup-actions">
          <button
            disabled={
              loading ||
              busy ||
              recording !== null ||
              samples.filter(Boolean).length !== SAMPLE_COUNT ||
              voice?.model_available === false
            }
            onClick={() => void submit()}
          >
            {busy
              ? "Saving…"
              : referenceSaved
                ? "Replace saved voice"
                : "Save user’s voice"}
          </button>
          <p className="muted">
            The voice reference stays on this device’s Remind server. Setup
            recordings are discarded after processing.
          </p>
        </div>
      </section>
      {referenceSaved && (
        <button
          className="danger"
          disabled={busy || recording !== null}
          onClick={() => void remove()}
        >
          Remove saved voice
        </button>
      )}
    </main>
  );
}
