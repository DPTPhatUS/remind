export type AuthTokenResponse = {
  access_token: string
  token_type: "bearer" | string
  expires_at: string
}

export type CurrentUser = {
  id: string
  email: string
  display_name: string
  role: "admin" | string
}

export type Patient = {
  id: string
  display_name: string
  date_of_birth: string | null
  preferences: Record<string, unknown>
  accessibility_settings: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type RecognitionStatus =
  | "unknown"
  | "seen_before"
  | "introduced"
  | "confirmed"
  | "trusted"
  | "opted_out"

export type Person = {
  id: string
  patient_id: string
  display_name: string
  relationship_to_patient: string | null
  notes: string | null
  recognition_status: RecognitionStatus
  consent_status: string
  sensitive: boolean
  created_at: string
  updated_at: string
}

export type Relationship = {
  id: string
  patient_id: string
  from_person_id: string
  to_person_id: string | null
  relationship_type: string
  confidence: number
  confirmed_by_user_id: string | null
  source_claim_id: string | null
  created_at: string
  updated_at: string
}

export type MemoryEvent = {
  id: string
  patient_id: string
  title: string
  description: string | null
  event_date: string | null
  confidence: number
  emotional_importance: string
  patient_visible: boolean
  created_at: string
  updated_at: string
}

export type Interaction = {
  id: string
  patient_id: string
  started_at: string
  ended_at: string | null
  summary: string | null
  confidence: number
  status: string
  created_at: string
  updated_at: string
}

export type ReviewItem = {
  id: string
  patient_id: string
  item_type: string
  target_type: string
  target_id: string
  title: string
  summary: string | null
  payload: Record<string, unknown>
  status: string
  created_at: string
  updated_at: string
}

export type MemoryClaim = {
  id: string
  patient_id: string
  subject_type: string
  subject_id: string
  claim_text: string
  structured_value: Record<string, unknown>
  source_type: string
  source_id: string
  confidence: number
  confirmed_by_user_id: string | null
  patient_visible: boolean
  created_at: string
  updated_at: string
}

export type ReminderPayload = {
  title: string
  lines: string[]
  patient_visible?: boolean
  requires_review?: boolean
}

export type FaceBox = {
  probability: number
  x_min: number
  y_min: number
  x_max: number
  y_max: number
}

export type RecognitionUpdatePayload = {
  subject: string
  similarity: number
  face_probability: number
  box: FaceBox
  reminder?: ReminderPayload
}

export type LiveServerMessage =
  | { type: "session.ready"; payload: { session_id: string } }
  | {
      type: "media.accepted"
      payload: { media_type: "frame" | "audio" | string; content_type: string; size_bytes: number }
    }
  | { type: "recognition.update"; payload: RecognitionUpdatePayload }
  | { type: "reminder.update"; payload: ReminderPayload }
  | {
      type: "interaction.candidate"
      payload: { confidence: number; reason: string }
    }
  | {
      type: "interaction.started"
      payload: {
        interaction_id: string
        confidence: number
        reason: string
        candidate_ms: number
      }
    }
  | {
      type: "transcript.received"
      payload: {
        interaction_id: string
        content_type: string
        size_bytes: number
        text: string
        started_at_ms: number
        ended_at_ms: number
      }
    }
  | {
      type: "interaction.ended"
      payload: {
        interaction_id: string
        confidence: number
        duration_ms: number
        reason: string
      }
    }
  | {
      type: "interaction.marked"
      payload: { marker: string }
    }
  | {
      type: "session.error"
      payload: { message: string }
    }
