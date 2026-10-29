"""In-memory pipeline contracts; SQL rows and provider validation stay separate."""

from typing import Literal, NotRequired, TypedDict

VoiceRole = Literal["user", "visitor", "uncertain"]


class PendingAssociation(TypedDict):
    status: Literal["pending"]
    reason: NotRequired[str]
    visitor_id: NotRequired[None]
    encounter_id: NotRequired[None]


class UnattributedAssociation(TypedDict):
    status: Literal["unattributed"]
    reason: str
    visitor_id: None
    encounter_id: None


class AttributedAssociation(TypedDict):
    status: Literal["attributed"]
    reason: str
    visitor_id: str
    encounter_id: str
    person_version: int | None


Association = PendingAssociation | UnattributedAssociation | AttributedAssociation


class SpeechInterval(TypedDict):
    start_ms: float
    end_ms: float


class RawTranscriptTurn(SpeechInterval):
    id: str
    text: str
    speaker: NotRequired[str | None]


class TranscriptTurn(RawTranscriptTurn):
    role: VoiceRole
    voice_score: NotRequired[float]
    association: NotRequired[Association]


class TimelinePoint(TypedDict):
    ms: float
    eligible: bool
    reason: str
    candidate_id: NotRequired[str | None]
    encounter_id: NotRequired[str | None]
    visitor_id: NotRequired[str | None]
    person_version: NotRequired[int | None]
    voice_version: NotRequired[int | None]
    face_count: NotRequired[int]
    eligible_until: NotRequired[float]


Metrics = dict[str, int | float]


class AudioResult(TypedDict):
    segments: list[TranscriptTurn]
    metrics: Metrics
    voice_ready: bool
    has_speech: NotRequired[bool]
    status: NotRequired[str]


class LearningPayload(TypedDict):
    visitor_id: str
    person_version: int | None
    voice_version: int | None
    segment_ids: list[str]
    start_ms: float
    end_ms: float


class AudioClipInput(TypedDict):
    path: str | None
    voice_version: int | None


class LearningClipInput(TypedDict):
    voice_ready: int
    input_kind: Literal["media", "conversation"]
    received_ms: int
    audio_completed_ms: int
    attribution_finalized_ms: int


class JobFields(TypedDict):
    id: str
    clip_id: str
    lease_token: str


class AudioJob(JobFields):
    kind: Literal["audio"]
    clip: AudioClipInput


class LearningJob(JobFields):
    kind: Literal["learning"]
    encounter_id: str
    payload: LearningPayload
    clip: LearningClipInput


ClaimedJob = AudioJob | LearningJob
