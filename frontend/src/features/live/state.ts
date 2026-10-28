import type { LiveView } from "@/lib/api-types";

export function conversationStatus(jobs: readonly { status: string }[]) {
  const failed = jobs.filter((job) => job.status === "failed").length;
  const skipped = jobs.filter((job) => job.status === "skipped").length;
  const waiting = jobs.filter((job) => job.status === "waiting_for_attribution").length;
  const processing = jobs.filter((job) => job.status === "pending" || job.status === "running").length;
  const messages: string[] = [];
  if (failed)
    messages.push(`${failed} conversation clip(s) could not be processed. Learning continues with later recordings.`);
  if (skipped) messages.push(`${skipped} late recording(s) skipped.`);
  if (waiting)
    messages.push("Conversation transcribed; waiting to identify the visitor.");
  else if (processing)
    messages.push(`${processing} conversation clip(s) processing.`);
  return messages.join(" ");
}

export function pauseStaleView(current: LiveView | null, now: number): LiveView | null {
  if (!current) return current;
  const expired =
    current.encounter.absence_deadline_ms !== null &&
    now >= current.encounter.absence_deadline_ms;
  if (
    !current.detections.length &&
    current.encounter.reason === "stale_observations" &&
    (!expired || !current.encounter.memory)
  ) return current;
  return {
    detections: [],
    candidate: null,
    encounter: {
      ...current.encounter,
      state: "paused",
      learning_available: false,
      reason: "stale_observations",
      memory: expired ? null : current.encounter.memory,
      visitor_id: expired ? null : current.encounter.visitor_id,
      id: expired ? null : current.encounter.id,
    },
  };
}
