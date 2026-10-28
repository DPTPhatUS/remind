import { expect, it } from "vitest";
import type { LiveView, PersonMemory } from "@/lib/api-types";
import { conversationStatus, pauseStaleView } from "./state";

it("shows failures and skips without counting them as processing", () => {
  expect(conversationStatus([
    { status: "failed" }, { status: "failed" }, { status: "skipped" },
    { status: "pending" }, { status: "running" },
  ])).toBe("2 conversation clip(s) could not be processed. Learning continues with later recordings. 1 late recording(s) skipped. 2 conversation clip(s) processing.");
  expect(conversationStatus([{ status: "skipped" }])).toBe("1 late recording(s) skipped.");
  expect(conversationStatus([{ status: "done" }, { status: "cancelled" }])).toBe("");
});

const memory: PersonMemory = {
  id: "visitor", name: "James", relationship: null, age: null, notes: null,
  version: 1, created_at: "2026-10-28T00:00:00Z", profile_summary: null,
  highlights: [], last_encounter: null, encounters: [], facts: [],
};

function view(): LiveView {
  return {
    detections: [{ box: [0.1, 0.1, 0.5, 0.5], quality: true }],
    candidate: {
      id: "candidate", person_id: "visitor", box: [0.1, 0.1, 0.5, 0.5],
      confirmed: true, quality: true,
    },
    encounter: {
      id: "encounter", visitor_id: "visitor", state: "confirmed",
      learning_available: true, reason: "direct_confirmation",
      absence_deadline_ms: 5000, memory,
    },
  };
}

it("shows attribution waits alongside failures and ordinary processing otherwise", () => {
  expect(conversationStatus([{ status: "failed" }, { status: "waiting_for_attribution" }]))
    .toBe("1 conversation clip(s) could not be processed. Learning continues with later recordings. Conversation transcribed; waiting to identify the visitor.");
  expect(conversationStatus([{ status: "waiting_for_attribution" }, { status: "pending" }]))
    .toBe("Conversation transcribed; waiting to identify the visitor.");
  expect(conversationStatus([{ status: "running" }])).toBe("1 conversation clip(s) processing.");
  expect(conversationStatus([])).toBe("");
});

it("pauses stale observations without mutating the received view or losing an unexpired reminder", () => {
  const current = view();
  const stale = pauseStaleView(current, 4999);
  expect(stale).toEqual({
    detections: [], candidate: null,
    encounter: {
      ...current.encounter, state: "paused", learning_available: false, reason: "stale_observations",
    },
  });
  expect(current).toEqual(view());
  expect(stale?.encounter.memory).toBe(memory);
  expect(pauseStaleView(stale, 4999)).toBe(stale);
});

it("clears the reminder and selected encounter at the exact absence deadline", () => {
  const stale = pauseStaleView(view(), 4999);
  expect(pauseStaleView(stale, 5000)?.encounter).toEqual({
    id: null, visitor_id: null, state: "paused", learning_available: false,
    reason: "stale_observations", absence_deadline_ms: 5000, memory: null,
  });
});

it("keeps null views and stable paused views unchanged", () => {
  expect(pauseStaleView(null, 5000)).toBeNull();
  const current = view();
  current.encounter.absence_deadline_ms = null;
  const stale = pauseStaleView(current, 9000);
  expect(stale?.encounter.memory).toBe(memory);
  expect(pauseStaleView(stale, 10000)).toBe(stale);
});
