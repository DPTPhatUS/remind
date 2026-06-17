import type {
  LiveServerMessage,
  RecognitionUpdatePayload,
  ReminderPayload,
} from "@/lib/api-types"

export type LiveReminder = {
  title: string
  lines: string[]
}

export type RecognitionChip = RecognitionUpdatePayload & {
  label: string
}

export type LiveState = {
  sessionId: string | null
  reminder: LiveReminder | null
  recognitions: RecognitionChip[]
  requiresReview: boolean
  media: {
    frameAccepted: boolean
    audioAccepted: boolean
  }
  interaction: {
    status: "idle" | "candidate" | "active" | "ended"
    interactionId: string | null
    reason: string | null
  }
  latestTranscript: string | null
  error: string | null
}

export function createInitialLiveState(): LiveState {
  return {
    sessionId: null,
    reminder: null,
    recognitions: [],
    requiresReview: false,
    media: {
      frameAccepted: false,
      audioAccepted: false,
    },
    interaction: {
      status: "idle",
      interactionId: null,
      reason: null,
    },
    latestTranscript: null,
    error: null,
  }
}

export function normalizeLiveEvents(
  payload: LiveServerMessage | LiveServerMessage[]
): LiveServerMessage[] {
  return Array.isArray(payload) ? payload : [payload]
}

export function reduceLiveEvent(
  state: LiveState,
  event: LiveServerMessage
): LiveState {
  switch (event.type) {
    case "session.ready":
      return { ...state, sessionId: event.payload.session_id, error: null }
    case "media.accepted":
      return {
        ...state,
        media: {
          frameAccepted:
            state.media.frameAccepted || event.payload.media_type === "frame",
          audioAccepted:
            state.media.audioAccepted || event.payload.media_type === "audio",
        },
      }
    case "recognition.update": {
      const reminder = event.payload.reminder
      return {
        ...state,
        recognitions: upsertRecognition(state.recognitions, event.payload),
        ...(reminder ? reminderState(reminder) : {}),
      }
    }
    case "reminder.update":
      return { ...state, ...reminderState(event.payload) }
    case "interaction.candidate":
      return {
        ...state,
        interaction: {
          status: "candidate",
          interactionId: state.interaction.interactionId,
          reason: event.payload.reason,
        },
      }
    case "interaction.started":
      return {
        ...state,
        interaction: {
          status: "active",
          interactionId: event.payload.interaction_id,
          reason: event.payload.reason,
        },
      }
    case "transcript.received":
      return { ...state, latestTranscript: event.payload.text }
    case "interaction.ended":
      return {
        ...state,
        interaction: {
          status: "ended",
          interactionId: event.payload.interaction_id,
          reason: event.payload.reason,
        },
      }
    case "session.error":
      return { ...state, error: event.payload.message }
    default:
      return state
  }
}

function reminderState(reminder: ReminderPayload): Partial<LiveState> {
  if (reminder.patient_visible === false) {
    return {
      reminder: null,
      requiresReview: Boolean(reminder.requires_review),
    }
  }

  return {
    reminder: {
      title: reminder.title,
      lines: reminder.lines,
    },
    requiresReview: Boolean(reminder.requires_review),
  }
}

function upsertRecognition(
  recognitions: RecognitionChip[],
  recognition: RecognitionUpdatePayload
) {
  const chip = {
    ...recognition,
    label: recognition.reminder?.title ?? "Seen before",
  }
  const others = recognitions.filter((item) => item.subject !== recognition.subject)
  return [chip, ...others].slice(0, 5)
}
