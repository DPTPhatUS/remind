import { describe, expect, it } from "vitest"

import {
  createInitialLiveState,
  normalizeLiveEvents,
  reduceLiveEvent,
} from "@/features/live/live-events"
import type { LiveServerMessage } from "@/lib/api-types"

describe("live event reducer", () => {
  it("normalizes single event and event array websocket payloads", () => {
    const event: LiveServerMessage = {
      type: "session.ready",
      payload: { session_id: "abc" },
    }

    expect(normalizeLiveEvents(event)).toEqual([event])
    expect(normalizeLiveEvents([event])).toEqual([event])
  })

  it("uses patient-visible reminders as the main reminder", () => {
    const state = reduceLiveEvent(createInitialLiveState(), {
      type: "reminder.update",
      payload: {
        title: "This may be David.",
        lines: ["He introduced himself as your neighbor."],
        patient_visible: true,
      },
    })

    expect(state.reminder?.title).toBe("This may be David.")
  })

  it("hides non-patient-visible reminders", () => {
    const state = reduceLiveEvent(
      {
        ...createInitialLiveState(),
        reminder: { title: "Anna", lines: ["Your daughter"] },
      },
      {
        type: "reminder.update",
        payload: {
          title: "Sensitive profile",
          lines: [],
          patient_visible: false,
        },
      },
    )

    expect(state.reminder).toBeNull()
  })

  it("tracks recognition chips and active interaction status", () => {
    const withRecognition = reduceLiveEvent(createInitialLiveState(), {
      type: "recognition.update",
      payload: {
        subject: "subject-1",
        similarity: 0.97,
        face_probability: 0.99,
        box: { probability: 0.99, x_min: 1, y_min: 2, x_max: 3, y_max: 4 },
        reminder: {
          title: "Anna",
          lines: ["Your daughter"],
          patient_visible: true,
        },
      },
    })
    const active = reduceLiveEvent(withRecognition, {
      type: "interaction.started",
      payload: {
        interaction_id: "interaction-1",
        confidence: 0.8,
        reason: "stable_face_and_speech",
        candidate_ms: 2100,
      },
    })

    expect(active.recognitions).toHaveLength(1)
    expect(active.interaction.status).toBe("active")
    expect(active.interaction.interactionId).toBe("interaction-1")
  })

  it("surfaces session errors without clearing other state", () => {
    const state = reduceLiveEvent(
      {
        ...createInitialLiveState(),
        reminder: { title: "Anna", lines: ["Your daughter"] },
        recognitions: [
          {
            subject: "subject-1",
            label: "Anna",
            similarity: 0.97,
            face_probability: 0.99,
            box: { probability: 0.99, x_min: 1, y_min: 2, x_max: 3, y_max: 4 },
          },
        ],
      },
      {
        type: "session.error",
        payload: { message: "Recognition model timeout" },
      },
    )

    expect(state.error).toBe("Recognition model timeout")
    expect(state.reminder).not.toBeNull()
    expect(state.recognitions).toHaveLength(1)
  })
})
