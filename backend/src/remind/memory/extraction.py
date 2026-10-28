"""Structured, evidence-backed conversational memories.

Language understanding belongs to two separate model passes. This module applies
source, speaker-role and write-scope checks without restricting natural English to
specific introductions or sentence patterns.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from remind.database import Record
from remind.memory.association import eligible_source


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    quote: str = Field(min_length=1, max_length=2000)


class FactFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    polarity: Literal["affirmative", "negative"] = Field(
        description="Whether the visitor asserts or denies this predicate/value."
    )
    temporal_status: Literal["current", "past", "planned"]
    valid_from: str | None
    valid_to: str | None
    operation: Literal["add", "correct", "change"]
    target_fact_id: str | None
    evidence: list[Evidence] = Field(min_length=1, max_length=12)


class NameFact(FactFields):
    category: Literal["identity"]
    predicate: Literal["name"]


class AgeFact(FactFields):
    category: Literal["age"]
    predicate: Literal["age"]
    value: str = Field(
        min_length=1,
        max_length=500,
        description="Stated age: digits for an exact age, preserving stated approximations.",
    )


class RelationshipFact(FactFields):
    subject: Literal["visitor"]
    category: Literal["relationship"]
    predicate: Literal["relationship"]


class BackgroundFact(FactFields):
    category: Literal[
        "work",
        "education",
        "residence",
        "interests",
        "preferences",
        "routines",
        "family",
        "experiences",
        "plans",
        "other",
    ]
    predicate: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")


# A plain union emits anyOf, which the provider's structured-output schema supports.
ProposedFact = NameFact | AgeFact | RelationshipFact | BackgroundFact
FACT_ADAPTER: TypeAdapter[ProposedFact] = TypeAdapter(ProposedFact)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=700)
    facts: list[ProposedFact] = Field(max_length=40)


class FactAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_index: int = Field(ge=0)
    supported: bool
    affirmative: bool = Field(
        description="The visitor asserts this value; a denial alone is not affirmative support."
    )
    reason: str = Field(max_length=500)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessments: list[FactAssessment]


def normalize(value: str) -> str:
    return " ".join(value.split())


def validate_extraction(
    result: Record,
    segments: Sequence[Mapping[str, Any]],
    verification: Record,
    existing_facts: Sequence[Record] = (),
    current_ids: Collection[str] | None = None,
    *,
    visitor_id: str | None,
    encounter_id: str,
) -> Record:
    """Allow only separately verified claims with genuine visitor evidence.

    `segments` may include bounded prior dialogue from this encounter. Evidence
    identifiers are global, so quotes in adjacent clips cannot be confused.
    A claim must cite at least one current segment, preventing old dialogue from
    being repeatedly treated as newly observed information.
    """
    indexed = {s["id"]: s for s in segments}
    known = {f["id"]: f for f in existing_facts}
    assessments = verification.get("assessments", [])
    # Duplicate or contradictory assessments are not affirmative verification.
    counts: dict[int, int] = {}
    approved: set[int] = set()
    for assessment in assessments:
        idx = assessment.get("fact_index")
        if type(idx) is not int:
            continue
        counts[idx] = counts.get(idx, 0) + 1
        if assessment.get("supported") is True and assessment.get("affirmative") is True:
            approved.add(idx)
    accepted: list[Record] = []
    for idx, proposed in enumerate(result.get("facts", [])):
        if idx not in approved or counts.get(idx) != 1:
            continue
        try:
            fact = FACT_ADAPTER.validate_python(proposed).model_dump()
        except (ValidationError, TypeError):
            continue
        if fact.pop("polarity") != "affirmative":
            continue
        if fact["category"] not in {"identity", "age", "relationship"} and fact["predicate"] in {
            "name",
            "age",
            "relationship",
        }:
            # A misplaced core field invalidates this claim, not valid sibling claims.
            continue
        fact["subject"] = normalize(fact["subject"])
        fact["predicate"] = normalize(fact["predicate"])
        fact["value"] = normalize(fact["value"])
        if not all(fact[k] for k in ("subject", "predicate", "value")):
            continue
        sources = []
        valid = True
        for evidence in fact["evidence"]:
            source = indexed.get(evidence["segment_id"])
            quote = evidence["quote"].strip()
            if (
                source is None
                or source.get("role") not in {"user", "visitor"}
                or not visitor_id
                or not eligible_source(source, visitor_id, encounter_id)
                or not quote
                or quote not in source.get("text", "")
            ):
                valid = False
                break
            evidence["quote"] = quote
            sources.append(source)
        if not valid or not any(s.get("role") == "visitor" for s in sources):
            continue
        if current_ids is not None and not any(s["id"] in current_ids for s in sources):
            continue
        target = fact["target_fact_id"]
        if fact["operation"] == "add":
            if target is not None:
                continue
        elif (
            target not in known
            or known[target].get("subject") != fact["subject"]
            or known[target].get("predicate") != fact["predicate"]
            or known[target].get("manual")
        ):
            continue
        accepted.append(fact)
    return {"summary": str(result.get("summary", ""))[:700], "facts": accepted}
