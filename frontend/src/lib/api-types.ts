export type Person = {
  id: string;
  name: string | null;
  relationship: string | null;
  age: string | null;
  notes: string | null;
  version: number;
  created_at: string;
  profile_summary: string | null;
  highlights: string[];
};
export type Encounter = {
  id: string;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
};
export type Fact = {
  id: string;
  subject: string;
  category:
    | "identity"
    | "relationship"
    | "age"
    | "work"
    | "education"
    | "residence"
    | "interests"
    | "preferences"
    | "routines"
    | "family"
    | "experiences"
    | "plans"
    | "other";
  predicate: string;
  value: string;
  temporal_status: "current" | "past" | "planned";
  valid_from: string | null;
  valid_to: string | null;
  evidence: { segment_id: string; quote: string }[];
  status: "accepted" | "conflict" | "superseded" | "dismissed";
  manual: boolean;
  created_at: string;
  updated_at: string;
};
export type VoiceStatus = {
  ready: boolean;
  reference_saved: boolean;
  model_available: boolean;
  error: string | null;
  version: number;
  model: string | null;
  sample_count: number;
  updated_at: string | null;
};
export type SessionStatus = {
  generation: string;
  memory_available: boolean;
  voice_ready: boolean;
  profile_learning_available: boolean;
};
export type PersonMemory = Person & {
  last_encounter: Encounter | null;
  encounters: Encounter[];
  facts: Fact[];
};
export type FaceTrack = {
  track_id: string;
  person_id: string | null;
  box: [number, number, number, number];
  state: string;
  memory: PersonMemory | null;
};
export type VisionMessage = {
  type: "vision";
  generation: string;
  sequence: number;
  capture_ms: number;
  tracks: FaceTrack[];
  processing_ms: number;
  processed_fps: number;
  dropped: number;
};
