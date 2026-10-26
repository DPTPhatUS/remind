"""Structured, evidence-backed conversational memories.

Language understanding belongs to two independent model passes. This module applies
source, speaker-role and write-scope checks without restricting natural English to
specific introductions or sentence patterns.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Category = Literal[
    "identity", "relationship", "age", "work", "education", "residence", "interests",
    "preferences", "routines", "family", "experiences", "plans", "other",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    quote: str = Field(min_length=1, max_length=2000)


class ProposedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=100)
    category: Category
    predicate: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)
    temporal_status: Literal["current", "past", "planned"]
    valid_from: str | None
    valid_to: str | None
    operation: Literal["add", "correct", "change"]
    target_fact_id: str | None
    evidence: list[Evidence] = Field(min_length=1, max_length=12)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=700)
    facts: list[ProposedFact] = Field(max_length=40)


class FactAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_index: int = Field(ge=0)
    supported: bool
    reason: str = Field(max_length=500)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessments: list[FactAssessment]


def normalize(value):
    return " ".join(str(value).split())


def validate_extraction(result, segments, verification, existing_facts=(), current_ids=None):
    """Allow only independently verified claims with genuine visitor evidence.

    `segments` may include bounded prior dialogue from this encounter. Evidence
    identifiers are global, so quotes in adjacent clips cannot be confused.
    A claim must cite at least one current segment, preventing old dialogue from
    being repeatedly treated as newly observed information.
    """
    indexed = {s["id"]: s for s in segments}
    known = {f["id"]: f for f in existing_facts}
    assessments = verification.get("assessments", [])
    # Duplicate or contradictory assessments are not affirmative verification.
    counts = {}
    approved = set()
    for assessment in assessments:
        idx = assessment.get("fact_index")
        if type(idx) is not int:
            continue
        counts[idx] = counts.get(idx, 0) + 1
        if assessment.get("supported") is True:
            approved.add(idx)
    accepted = []
    for idx, proposed in enumerate(result.get("facts", [])):
        if idx not in approved or counts.get(idx) != 1:
            continue
        try:
            fact = ProposedFact.model_validate(proposed).model_dump()
        except (ValidationError, TypeError):
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
