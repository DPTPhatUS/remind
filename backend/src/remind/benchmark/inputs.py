"""Current input contracts for the four benchmark paths."""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["audio", "conversation", "face", "video"]
Time = Annotated[float, Field(ge=0, strict=True, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Interval(Input):
    start_ms: Time
    end_ms: Time

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("Intervals require start_ms < end_ms")
        return self


class Source(Input):
    id: Text
    description: Text
    usage_terms: Text
    url: str = ""


class Media(Input):
    id: Text
    path: Path
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    source_id: Text
    source_start_ms: Time
    source_end_ms: Time
    preprocessing: list[str] = Field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return self.source_end_ms - self.source_start_ms

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.duration_ms <= 0:
            raise ValueError("Media requires source_start_ms < source_end_ms")
        return self


class Turn(Interval):
    id: Text
    role: Literal["user", "visitor", "uncertain"]
    text: Text
    overlap: bool = False
    offscreen: bool = False


class Visibility(Interval):
    visitor_id: str | None
    face_count: Annotated[int, Field(ge=0, strict=True)]

    @model_validator(mode="after")
    def identity_is_unambiguous(self) -> Self:
        if self.visitor_id is not None and self.face_count != 1:
            raise ValueError("Identity annotations require exactly one visible face")
        return self


class Evidence(Interval):
    quote: Text


class ExpectedFact(Input):
    id: Text
    subject: Text
    predicate: Text
    value: Text
    temporal_status: Literal["current", "past", "planned"] = "current"
    status: Literal["accepted", "conflict", "superseded", "dismissed"] = "accepted"
    present: bool = True
    evidence: list[Evidence] = Field(default_factory=list)


def validate_fact_labels(facts: list[ExpectedFact]) -> None:
    seen: dict[tuple[str, ...], bool] = {}
    for fact in facts:
        key = tuple(
            " ".join(getattr(fact, field).split()).casefold()
            for field in ("subject", "predicate", "value", "temporal_status", "status")
        )
        if key in seen and seen[key] != fact.present:
            raise ValueError("A fact cannot be both expected and forbidden")
        seen[key] = fact.present


def unique_ids(items: list, label: str) -> None:
    if len({item.id for item in items}) != len(items):
        raise ValueError(f"Duplicate {label} IDs")


def annotations_fit(media: Media, intervals: list[Interval]) -> None:
    if any(interval.end_ms > media.duration_ms for interval in intervals):
        raise ValueError("Annotations must fit within their media")


class AudioRecording(Media):
    turns: list[Turn] = Field(default_factory=list)

    @model_validator(mode="after")
    def annotations(self) -> Self:
        unique_ids(self.turns, "turn")
        annotations_fit(self, list(self.turns))
        return self


class FaceEncounter(Media):
    visitor_id: Text
    visible: list[Visibility] = Field(default_factory=list)

    @model_validator(mode="after")
    def visibility_annotations(self) -> Self:
        annotations_fit(self, list(self.visible))
        ordered = sorted(self.visible, key=lambda item: item.start_ms)
        if any(a.end_ms > b.start_ms for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("Visibility annotations must not overlap")
        return self


class VideoEncounter(FaceEncounter):
    turns: list[Turn] = Field(default_factory=list)
    facts: list[ExpectedFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def dialogue_annotations(self) -> Self:
        unique_ids(self.turns, "turn")
        unique_ids(self.facts, "fact")
        validate_fact_labels(self.facts)
        annotations_fit(self, [*self.turns, *(e for f in self.facts for e in f.evidence)])
        return self


class Batch(Interval):
    id: Text
    turns: Annotated[list[Turn], Field(min_length=1)]

    @model_validator(mode="after")
    def turns_fit(self) -> Self:
        unique_ids(self.turns, "turn")
        if any(t.start_ms < self.start_ms or t.end_ms > self.end_ms for t in self.turns):
            raise ValueError("Transcript turns must fit inside their batch")
        return self


class TextEncounter(Input):
    id: Text
    started_at: datetime
    batches: Annotated[list[Batch], Field(min_length=1)]

    @model_validator(mode="after")
    def ordered_batches(self) -> Self:
        if self.started_at.utcoffset() is None:
            raise ValueError("Encounter dates require a timezone")
        unique_ids(self.batches, "batch")
        unique_ids([t for batch in self.batches for t in batch.turns], "turn")
        if any(a.end_ms > b.start_ms for a, b in zip(self.batches, self.batches[1:], strict=False)):
            raise ValueError("Transcript batches must be ordered and must not overlap")
        return self


class Case(Input):
    id: Text


class AudioCase(Case):
    enrollment: list[Media] = Field(default_factory=list)
    recordings: Annotated[list[AudioRecording], Field(min_length=1)]


class ConversationCase(Case):
    encounters: Annotated[list[TextEncounter], Field(min_length=1)]
    facts: list[ExpectedFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def annotations(self) -> Self:
        unique_ids(self.encounters, "encounter")
        unique_ids(self.facts, "fact")
        validate_fact_labels(self.facts)
        if any(
            a.started_at > b.started_at
            for a, b in zip(self.encounters, self.encounters[1:], strict=False)
        ):
            raise ValueError("Text encounters must be chronological")
        return self


class FaceCase(Case):
    encounters: Annotated[list[FaceEncounter], Field(min_length=1)]


class VideoCase(Case):
    enrollment: list[Media] = Field(default_factory=list)
    encounters: Annotated[list[VideoEncounter], Field(min_length=1)]


class Manifest(Input):
    title: Text
    annotation_notes: Text
    sources: list[Source] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AudioManifest(Manifest):
    cases: Annotated[list[AudioCase], Field(min_length=1)]


class ConversationManifest(Manifest):
    cases: Annotated[list[ConversationCase], Field(min_length=1)]


class FaceManifest(Manifest):
    cases: Annotated[list[FaceCase], Field(min_length=1)]


class VideoManifest(Manifest):
    cases: Annotated[list[VideoCase], Field(min_length=1)]


CONTRACTS = {
    "audio": AudioManifest,
    "conversation": ConversationManifest,
    "face": FaceManifest,
    "video": VideoManifest,
}


def load_manifest(
    kind: Kind, path: Path
) -> AudioManifest | ConversationManifest | FaceManifest | VideoManifest:
    manifest = CONTRACTS[kind].model_validate_json(path.read_bytes())
    assert isinstance(manifest, (AudioManifest, ConversationManifest, FaceManifest, VideoManifest))
    unique_ids(manifest.cases, "case")
    unique_ids(manifest.sources, "source")
    sources = {source.id for source in manifest.sources}
    media: list[Media] = []
    enrollment: list[Media] = []
    scored_media: list[Media] = []
    for case in manifest.cases:
        references = getattr(case, "enrollment", [])
        if references and not 3 <= len(references) <= 5:
            raise ValueError(
                "Enrollment requires three to five samples, or none for missing-reference tests"
            )
        if any(not 3000 <= sample.duration_ms <= 20000 for sample in references):
            raise ValueError("Enrollment samples must last between 3 and 20 seconds")
        reference_keys = [(r.source_id, r.source_start_ms, r.source_end_ms) for r in references]
        if len(set(reference_keys)) != len(reference_keys) or len(
            {r.sha256 for r in references}
        ) != len(references):
            raise ValueError("Enrollment samples must be separate passages")
        recordings = [
            *getattr(case, "recordings", []),
            *(e for e in getattr(case, "encounters", []) if isinstance(e, Media)),
        ]
        unique_ids([*references, *recordings], "media")
        enrollment.extend(references)
        scored_media.extend(recordings)
        media.extend([*references, *recordings])
    for sample in enrollment:
        for other in scored_media:
            if sample.sha256 == other.sha256 or (
                sample.source_id == other.source_id
                and (
                    sample.source_start_ms < other.source_end_ms
                    and other.source_start_ms < sample.source_end_ms
                )
            ):
                raise ValueError("Enrollment must not overlap scored media")
    for case in manifest.cases:
        references = getattr(case, "enrollment", [])
        for index, sample in enumerate(references):
            for other in references[index + 1 :]:
                if (
                    sample.source_id == other.source_id
                    and sample.source_start_ms < other.source_end_ms
                    and other.source_start_ms < sample.source_end_ms
                ):
                    raise ValueError("Enrollment passages must not overlap")
    for item in media:
        if item.source_id not in sources:
            raise ValueError(f"Undeclared media source: {item.source_id}")
        item.path = (path.resolve().parent / item.path).resolve()
        with item.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item.sha256:
            raise ValueError(f"Media checksum mismatch: {item.path}")
    return manifest
