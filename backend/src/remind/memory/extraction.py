import re

from pydantic import BaseModel, Field


class ProposedFact(BaseModel):
    person_id: str
    predicate: str
    value: str
    segment_ids: list[str]
    quote: str


class ExtractionResult(BaseModel):
    summary: str = Field(max_length=700)
    facts: list[ProposedFact]


def directly_supported(predicate, value, quote, text):
    # Deliberately narrow English self-statements. Free paraphrases stay in summaries.
    # A substring inside reported speech is not a direct statement.
    sentences = [part.strip() for part in re.split(r"[.!?]+\s*", text) if part.strip()]
    q = quote.strip().rstrip(".!?")
    if q not in sentences or re.search(
        r"\b(not|never|maybe|if|said|says|joking|pretend)\b", q, re.I
    ):
        return False
    v = re.escape(value.strip())
    patterns = {
        "name": rf"(?:My name is|I am|I'm) {v}",
        "relationship": rf"(?:I am|I'm) your {v}",
        "age": rf"(?:I am|I'm) {v}(?: years old)?",
        "notes": r"I (?:like|love|work|live|have|visit|enjoy) .+",
    }
    if predicate == "notes" and value.strip().rstrip(".!?") != q:
        return False
    return bool(re.fullmatch(patterns.get(predicate, r"(?!)"), q, re.I))


def validate_extraction(result, segments, mapping):
    indexed = {s["id"]: s for s in segments}
    accepted = []
    for fact in result.get("facts", []):
        sources = [indexed[s] for s in fact.get("segment_ids", []) if s in indexed]
        if not sources or len(sources) != len(fact.get("segment_ids", [])):
            continue
        if any(mapping.get(s["speaker"]) != fact["person_id"] for s in sources):
            continue
        quote = " ".join(fact.get("quote", "").split())
        text = " ".join(" ".join(s["text"] for s in sources).split())
        if (
            not quote
            or quote not in text
            or fact.get("predicate") not in {"name", "relationship", "age", "notes"}
        ):
            continue
        value = str(fact.get("value", "")).strip()
        if not value or len(value) > 500:
            continue
        if not directly_supported(fact["predicate"], value, quote, text):
            continue
        accepted.append(
            {
                "person_id": fact["person_id"],
                "predicate": fact["predicate"],
                "value": value,
                "evidence": {"segment_ids": fact["segment_ids"], "quote": quote},
            }
        )
    return {"summary": result.get("summary", "")[:700], "facts": accepted, "segments": segments}
