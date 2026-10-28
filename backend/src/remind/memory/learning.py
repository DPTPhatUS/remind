"""The text-learning stage shared by live jobs and transcript evaluation."""

import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from remind.audio.providers import Providers
from remind.config import Settings
from remind.database import Record
from remind.memory.association import eligible_source
from remind.memory.contracts import Metrics, TranscriptTurn
from remind.memory.extraction import validate_extraction
from remind.memory.store import MemoryStore

MAX_DIALOGUE_CHARS = 24000


def bounded_dialogue(segments: list[TranscriptTurn]) -> list[TranscriptTurn]:
    """Keep the newest complete turns within the extraction input budget."""
    dialogue: list[TranscriptTurn] = []
    chars = 0
    for segment in reversed(segments):
        size = len(segment.get("text", ""))
        if chars + size > MAX_DIALOGUE_CHARS:
            break
        dialogue.append(segment)
        chars += size
    dialogue.reverse()
    return dialogue


async def learn_conversation(
    store: MemoryStore,
    providers: Providers,
    settings: Settings,
    encounter_id: str,
    visitor_id: str | None,
    segments: list[TranscriptTurn],
    start_ms: float,
    *,
    can_learn: bool,
) -> Record:
    metrics: Metrics = {}
    encounter = await store.get_encounter(encounter_id) or {}
    encounter_time = encounter.get("started_at") or ""
    if encounter_time:
        stamp = datetime.fromisoformat(encounter_time)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        encounter_time = stamp.astimezone(ZoneInfo(settings.memory_timezone)).isoformat()
    context = await store.recent_context(encounter_id, limit=40, before_ms=start_ms)
    # Provider-facing roles cannot turn unassociated speech into visitor evidence.
    dialogue = bounded_dialogue(
        [
            {
                **s,
                "role": s["role"]
                if visitor_id and eligible_source(s, visitor_id, encounter_id)
                else "uncertain",
            }
            for s in context + segments
        ]
    )
    current_ids = {segment["id"] for segment in segments}
    facts = (await store.facts_for_person(visitor_id) if visitor_id else [])[:120]
    # A delayed old clip must not use a later summary as its context.
    previous_summary = ""
    if encounter.get("summary_order", -1) <= start_ms:
        previous_summary = encounter.get("summary") or ""

    phase = time.perf_counter()
    result = await providers.extract(
        dialogue,
        previous_summary,
        facts,
        encounter_time,
        current_ids,
    )
    metrics["extraction_ms"] = round((time.perf_counter() - phase) * 1000, 2)
    phase = time.perf_counter()
    verification: Record = {"assessments": []}
    if can_learn and any(segment.get("role") == "visitor" for segment in segments):
        verification = await providers.verify(result.get("facts", []), dialogue, facts)
    validated = validate_extraction(
        result,
        dialogue,
        verification,
        facts,
        current_ids=current_ids,
        visitor_id=visitor_id,
        encounter_id=encounter_id,
    )
    metrics["verification_ms"] = round((time.perf_counter() - phase) * 1000, 2)
    metrics.update(
        {
            "proposed_facts": len(result.get("facts", [])),
            "verified_facts": len(validated["facts"]),
            "visitor_segments": sum(s.get("role") == "visitor" for s in segments),
            "uncertain_segments": sum(s.get("role") == "uncertain" for s in segments),
        }
    )
    return {
        **validated,
        "segments": segments,
        "metrics": metrics,
        "proposals": result,
        "verification": verification,
    }
