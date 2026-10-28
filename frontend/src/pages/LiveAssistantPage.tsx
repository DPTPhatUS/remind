import { useState } from "react";
import { Link } from "react-router-dom";
import { useLiveSession } from "@/features/live/session";
import type { FaceBox, LiveEncounter } from "@/lib/api-types";

const cameraStatusLabels = {
  idle: "Camera is off",
  starting: "Starting camera…",
  live: "Camera is live",
  saving: "Saving conversation…",
};

function reminderLeft([left, , width]: FaceBox) {
  const cardWidth = "var(--face-card-width)";
  const preferredLeft =
    left > 0.5
      ? `calc(${left * 100}% - ${cardWidth} - 10px)`
      : `calc(${(left + width) * 100}% + 10px)`;
  return `clamp(8px, ${preferredLeft}, calc(100% - ${cardWidth} - 8px))`;
}

function VisitorReminder({ encounter }: { encounter: LiveEncounter }) {
  const memory = encounter.memory;
  return (
    <>
      <strong>
        {memory?.name ??
          (encounter.visitor_id
            ? "Someone you’ve met"
            : "Getting to know this person")}
      </strong>
      {encounter.state === "absent" && <small>Temporarily out of view</small>}
      {encounter.state === "paused" && (
        <small>Personal details learning is paused</small>
      )}
      {memory?.relationship && <span>{memory.relationship}</span>}
      {memory?.age && <span>Age stated: {memory.age}</span>}
      {memory?.highlights.length ? (
        <ul className="face-highlights">
          {memory.highlights.slice(0, 3).map((highlight) => (
            <li key={highlight}>{highlight}</li>
          ))}
        </ul>
      ) : null}
      {memory?.last_encounter && (
        <p>
          <small>
            Last met{" "}
            {new Date(memory.last_encounter.started_at).toLocaleDateString()}
          </small>
          {memory.last_encounter.summary ?? "No conversation summary recorded."}
        </p>
      )}
    </>
  );
}

export function LiveAssistantPage() {
  const {
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
  } = useLiveSession();
  const [aspect, setAspect] = useState(16 / 9);
  return (
    <main className="live-page">
      <div className="live-toolbar">
        <div>
          <h1>Your view</h1>
          <p>People and moments, remembered.</p>
        </div>
        {status === "idle" ? (
          <button onClick={() => void start()}>Start camera</button>
        ) : (
          <button
            className="secondary"
            disabled={status === "saving"}
            onClick={() => void stop()}
          >
            {status === "saving" ? "Saving…" : "Stop camera"}
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="camera-stage">
        <div
          className="camera-frame"
          style={{ aspectRatio: aspect, width: `min(100%, ${72 * aspect}vh)` }}
        >
          <video
            onLoadedMetadata={(event) =>
              setAspect(
                event.currentTarget.videoWidth /
                  event.currentTarget.videoHeight,
              )
            }
            ref={attachVideo}
            autoPlay
            playsInline
            muted
            aria-label="Live camera view"
          />
          {status === "idle" && (
            <div className="camera-empty">
              <span className="camera-symbol">◎</span>
              <h2>Keep familiar faces close.</h2>
              <p>
                Start the camera to recognize people and remember conversations.
              </p>
            </div>
          )}
          {view?.detections.map((detection, index) => (
            <div key={index} className={`face-box ${view.candidate?.confirmed ? "known" : ""}`}
              style={{ left: `${detection.box[0] * 100}%`, top: `${detection.box[1] * 100}%`,
                width: `${detection.box[2] * 100}%`, height: `${detection.box[3] * 100}%` }} />
          ))}
          {view && (view.encounter.memory || view.candidate) && (
            <div
              className="face-card"
              style={{
                left: view.candidate && view.encounter.state !== "paused"
                  ? reminderLeft(view.candidate.box)
                  : "12px",
              }}
            >
              <VisitorReminder encounter={view.encounter} />
            </div>
          )}
        </div>
      </div>
      {view && (view.encounter.memory || view.candidate) && (
        <div className="mobile-reminders"><article className="visitor-reminder">
          <VisitorReminder encounter={view.encounter} />
        </article></div>
      )}
      <div className="live-footer">
        <span className={`status-dot ${status === "live" ? "active" : ""}`} />
        {cameraStatusLabels[status]}
        <span>
          {memoryStatus} {jobsStatus}
        </span>
      </div>
      {voiceReady === false && (
        <p className="setup-note">
          Personal details learning is paused until a helper completes{" "}
          <Link to="/setup">voice setup</Link>. Face recognition and available
          conversation summaries continue.
        </p>
      )}
      {uploadPaused && (
        <div className="upload-recovery">
          <button onClick={() => void retryUpload()}>
            Retry conversation upload
          </button>{" "}
          <button className="secondary" onClick={downloadClip}>
            Download unsaved clip
          </button>
        </div>
      )}
      <details className="diagnostics">
        <summary>Performance and memory status</summary>
        <p>
          {diagnostics.fps.toFixed(1)} processed fps ·{" "}
          {diagnostics.latency.toFixed(0)} ms result age ·{" "}
          {diagnostics.processing.toFixed(0)} ms processing ·{" "}
          {diagnostics.dropped} replaced frames
        </p>
        <p>
          Voice matching assumes a quiet conversation with one visitor.
          Background voices can be mistaken for that visitor. Recognition and
          voice thresholds need calibration on encounter recordings.
        </p>
      </details>
    </main>
  );
}
