import { useState } from "react";
import { useLiveSession } from "@/features/live/session";

export function LiveAssistantPage() {
  const {
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
          {tracks.map((track) => (
            <div
              key={track.track_id}
              className={`face-box ${track.person_id ? "known" : ""}`}
              style={{
                left: `${track.box[0] * 100}%`,
                top: `${track.box[1] * 100}%`,
                width: `${track.box[2] * 100}%`,
                height: `${track.box[3] * 100}%`,
              }}
            >
              <div
                className="face-card"
                style={{
                  top: track.box[1] > 0.3 ? "auto" : "100%",
                  bottom: track.box[1] > 0.3 ? "100%" : "auto",
                  left: track.box[0] > 0.65 ? "auto" : 0,
                  right: track.box[0] > 0.65 ? 0 : "auto",
                }}
              >
                <strong>
                  {track.memory?.name ??
                    (track.person_id
                      ? "Someone you’ve met"
                      : track.state === "ambiguous"
                        ? "Still identifying…"
                        : "Getting to know this person")}
                </strong>
                {track.memory?.relationship && (
                  <span>{track.memory.relationship}</span>
                )}
                {track.memory?.age && (
                  <span>Age stated: {track.memory.age}</span>
                )}
                {track.memory?.last_encounter && (
                  <p>
                    <small>
                      Last met{" "}
                      {new Date(
                        track.memory.last_encounter.started_at,
                      ).toLocaleDateString()}
                    </small>
                    {track.memory.last_encounter.summary ??
                      "No conversation summary recorded."}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="live-footer">
        <span className={`status-dot ${status === "live" ? "active" : ""}`} />
        {status === "live"
          ? "Camera is live"
          : status === "starting"
            ? "Starting camera…"
            : "Camera is off"}
        <span>
          {memoryStatus} {jobsStatus}
        </span>
      </div>
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
      {jobsStatus.includes("could not") && (
        <button className="secondary" onClick={() => void retryJobs()}>
          Retry failed conversations
        </button>
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
          Recognition and speaker thresholds need calibration on your encounter
          recordings.
        </p>
        <button className="secondary" onClick={exportTrace}>
          Download performance trace
        </button>
      </details>
    </main>
  );
}
