import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { VoiceStatus } from "@/lib/api-types";
import {
  useVoiceSamples,
  VOICE_SAMPLE_COUNT,
} from "@/features/voice/useVoiceSamples";

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
  const voiceSamples = useVoiceSamples();
  const { samples, recording, waitingForMicrophone, seconds } = voiceSamples;
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const referenceSaved = voice?.reference_saved ?? false;
  const generation = useRef(0);
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
    const lifecycle = generation;
    return () => {
      lifecycle.current++;
    };
  }, []);

  function record(index: number) {
    setError("");
    setNotice("");
    void voiceSamples.record(index);
  }

  function cancel() {
    voiceSamples.cancel();
    setNotice("Recording cancelled. You can try again when ready.");
  }

  async function submit() {
    const completeSamples = samples.filter((sample) => sample !== null);
    if (completeSamples.length !== VOICE_SAMPLE_COUNT) return;
    const token = ++generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const encoded = await Promise.all(
        completeSamples.map((sample) => audioBase64(sample.audio)),
      );
      if (token !== generation.current) return;
      const status = await api<VoiceStatus>("/user/voice", {
        method: "POST",
        body: JSON.stringify({ samples: encoded }),
      });
      if (token !== generation.current) return;
      setVoice(status);
      voiceSamples.clear();
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

  let voiceStatus = "User’s voice has not been set up";
  if (loading) voiceStatus = "Checking saved voice…";
  else if (voice?.ready) voiceStatus = "User’s voice is ready";
  else if (referenceSaved) voiceStatus = "Saved voice is temporarily unavailable";

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
      {(error || voiceSamples.error) && (
        <p role="alert" className="error">
          {error || voiceSamples.error}
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
          <strong>{voiceStatus}</strong>
          <p>
            {referenceSaved && voice ? (
              <>
                {voice.sample_count} samples saved
                {voice.updated_at && ` · ${new Date(voice.updated_at).toLocaleDateString()}`}.
                Record three new samples below to replace them.
              </>
            ) : (
              <>Face recognition and conversation summaries work without a saved
                voice. Learning personal facts starts after setup.</>
            )}
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
                    {waitingForMicrophone
                      ? "Waiting for microphone permission…"
                      : `Recording… ${seconds} seconds left`}
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
                  onClick={() => record(index)}
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
              samples.filter(Boolean).length !== VOICE_SAMPLE_COUNT ||
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
