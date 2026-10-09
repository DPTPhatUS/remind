export type Person = {
  id: string;
  name: string | null;
  relationship: string | null;
  age: string | null;
  notes: string | null;
  version: number;
  created_at: string;
};
export type Encounter = {
  id: string;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
};
export type Fact = {
  id: string;
  predicate: string;
  value: string;
  evidence: string;
  status: string;
  created_at: string;
};
export type PersonMemory = Person & {
  last_encounter: Encounter | null;
  encounters: Encounter[];
  facts: Fact[];
};
export type FaceTrack = {
  track_id: string;
  person_id: string | null;
  box: number[];
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
