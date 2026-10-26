import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { useLiveSession } from "@/features/live/session";
import type { FaceTrack } from "@/lib/api-types";

function VisitorReminder({ track }: { track: FaceTrack }) {
  return (
    <>
      <strong>
        {track.memory?.name ??
          (track.person_id
            ? "Someone you’ve met"
            : track.state === "ambiguous"
              ? "Still identifying…"
              : "Getting to know this person")}
      </strong>
      {track.memory?.relationship && <span>{track.memory.relationship}</span>}
      {track.memory?.age && <span>Age stated: {track.memory.age}</span>}
      {track.memory?.highlights.length ? (
        <ul className="face-highlights">
          {track.memory.highlights.slice(0, 3).map((highlight) => (
            <li key={highlight}>{highlight}</li>
          ))}
        </ul>
      ) : null}
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
            <Fragment key={track.track_id}>
              <div
                className={`face-box ${track.person_id ? "known" : ""}`}
                style={{
                  left: `${track.box[0] * 100}%`,
                  top: `${track.box[1] * 100}%`,
                  width: `${track.box[2] * 100}%`,
                  height: `${track.box[3] * 100}%`,
                }}
              />
              <div
                className="face-card"
                style={{
                  left: `clamp(8px, ${track.box[0] > 0.5 ? `calc(${track.box[0] * 100}% - clamp(150px, 20vw, 250px) - 10px)` : `calc(${(track.box[0] + track.box[2]) * 100}% + 10px)`}, calc(100% - clamp(150px, 20vw, 250px) - 8px))`,
                }}
              >
                <VisitorReminder track={track} />
              </div>
            </Fragment>
          ))}
        </div>
      </div>
      {tracks.length > 0 && (
        <div className="mobile-reminders">
          {tracks.map((track) => (
            <article className="visitor-reminder" key={track.track_id}>
              <VisitorReminder track={track} />
            </article>
          ))}
        </div>
      )}
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
          Voice matching assumes a quiet conversation with one visitor.
          Background voices can be mistaken for that visitor. Recognition and
          voice thresholds need calibration on encounter recordings.
        </p>
        <button className="secondary" onClick={exportTrace}>
          Download performance trace
        </button>
      </details>
    </main>
  );
}
