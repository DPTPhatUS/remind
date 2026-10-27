"""Scoring for roles, face associations, supported facts, evidence, and latency."""

import math
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np


def fraction(numerator: float, denominator: float) -> dict[str, int | float | None]:
    if (
        not math.isfinite(numerator)
        or not math.isfinite(denominator)
        or denominator < 0
        or (denominator == 0 and numerator != 0)
    ):
        raise ValueError("Invalid metric numerator/denominator")
    if isinstance(numerator, float) or isinstance(denominator, float):
        # Independently summed speech intervals can differ at floating-point boundaries.
        tolerance = max(1e-9, 8 * max(math.ulp(numerator), math.ulp(denominator)))
        if numerator < 0 and math.isclose(numerator, 0, rel_tol=0, abs_tol=tolerance):
            numerator = 0.0
        if numerator > denominator and math.isclose(
            numerator, denominator, rel_tol=0, abs_tol=tolerance
        ):
            numerator = denominator
    if not 0 <= numerator <= denominator:
        raise ValueError("Invalid metric numerator/denominator")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def percentiles(values: Sequence[float]) -> dict[str, int | float | None]:
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None, "max_ms": None}
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Latency values must be finite and non-negative")
    return {
        "count": len(values),
        "p50_ms": float(np.percentile(values, 50)),
        "p95_ms": float(np.percentile(values, 95)),
        "p99_ms": float(np.percentile(values, 99)),
        "max_ms": max(values),
    }


Record = dict[str, Any]
FactKey = tuple[str, str, str, str]
ROLES = ("user", "visitor", "uncertain")


def _normalized(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Scored facts require subject, predicate, value and temporal status")
    return " ".join(value.split()).casefold()


def _fact_key(fact: Record) -> FactKey:
    return (
        _normalized(fact.get("subject")),
        _normalized(fact.get("predicate")),
        _normalized(fact.get("value")),
        _normalized(fact.get("temporal_status", "current")),
    )


def score_facts(expected: Sequence[Record], actual: Sequence[Record]) -> Record:
    """Compare unique accepted claims; report forbidden and subject errors separately."""
    positives = {_fact_key(fact): fact for fact in expected if fact.get("present", True)}
    negatives = {_fact_key(fact): fact for fact in expected if not fact.get("present", True)}
    if positives.keys() & negatives.keys():
        raise ValueError("A fact cannot be both expected and forbidden")
    accepted = [fact for fact in actual if fact.get("status", "accepted") == "accepted"]
    saved = {_fact_key(fact): fact for fact in accepted}
    matched = [fact for key, fact in saved.items() if key in positives]
    missing = [fact for key, fact in positives.items() if key not in saved]
    wrong_subject = []
    unsupported = []
    for key, fact in saved.items():
        if key in positives:
            continue
        if any(key[1:] == wanted[1:] and key[0] != wanted[0] for wanted in positives):
            wrong_subject.append(fact)
        else:
            unsupported.append(fact)
    forbidden = [fact for key, fact in saved.items() if key in negatives]
    satisfied_absences = sum(key not in saved for key in negatives)
    return {
        "expected_count": len(positives),
        "actual_count": len(saved),
        "accepted_records": len(accepted),
        "duplicate_records": len(accepted) - len(saved),
        "raw_exact_precision": fraction(len(matched), len(saved)),
        "fact_coverage": fraction(len(matched), len(positives)),
        "required_absence": fraction(satisfied_absences, len(negatives)),
        "matched": matched,
        "missing_expected": missing,
        "unmatched_additions_require_review": unsupported,
        "wrong_subject_additions": wrong_subject,
        "forbidden_additions": forbidden,
    }


def _interval(turn: Record) -> tuple[float, float, str]:
    start, end = turn.get("start_ms"), turn.get("end_ms")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
    ):
        raise ValueError("Role intervals require finite times with 0 <= start_ms < end_ms")
    role = turn.get("role")
    if role not in ROLES:
        raise ValueError("Role labels must be user, visitor or uncertain")
    return float(start), float(end), role


def score_roles(expected_turns: Sequence[Record], actual_segments: Sequence[Record]) -> Record:
    """Score labelled speech duration, including misses and conflicting predictions.

    Splitting a transcript turn does not change its score. Overlapping predictions
    of different roles are conflicts, rather than a fabricated uncertain decision.
    Durations are summed per labelled turn, including overlapping annotations.
    A turn is correct only when its entire labelled interval has the right role.
    """
    predictions = [_interval(segment) for segment in actual_segments]
    totals = {
        "labelled_ms": 0.0,
        "covered_ms": 0.0,
        "correct_ms": 0.0,
        "wrong_role_ms": 0.0,
        "uncertain_ms": 0.0,
        "missed_ms": 0.0,
        "conflicting_ms": 0.0,
        "decisive_ms": 0.0,
        "correct_decisive_ms": 0.0,
    }
    turns: list[Record] = []
    per_role = {role: {"labelled_ms": 0.0, "correct_ms": 0.0} for role in ROLES}
    for turn in expected_turns:
        start, end, expected_role = _interval(turn)
        overlaps = [(a, b, role) for a, b, role in predictions if a < end and b > start]
        boundaries = sorted(
            {
                start,
                end,
                *(max(start, a) for a, _, _ in overlaps),
                *(min(end, b) for _, b, _ in overlaps),
            }
        )
        durations = {role: 0.0 for role in (*ROLES, "missing", "conflicting")}
        for left, right in zip(boundaries, boundaries[1:], strict=False):
            active = {role for a, b, role in overlaps if a < right and b > left}
            if not active:
                predicted = "missing"
            elif len(active) == 1:
                predicted = next(iter(active))
            else:
                predicted = "conflicting"
            durations[predicted] += right - left
        labelled = end - start
        correct = durations[expected_role]
        decisive = durations["user"] + durations["visitor"]
        correct_decisive = correct if expected_role in {"user", "visitor"} else 0.0
        totals["labelled_ms"] += labelled
        totals["covered_ms"] += labelled - durations["missing"]
        totals["correct_ms"] += correct
        totals["wrong_role_ms"] += decisive - correct_decisive
        totals["uncertain_ms"] += durations["uncertain"]
        totals["missed_ms"] += durations["missing"]
        totals["conflicting_ms"] += durations["conflicting"]
        totals["decisive_ms"] += decisive
        totals["correct_decisive_ms"] += correct_decisive
        per_role[expected_role]["labelled_ms"] += labelled
        per_role[expected_role]["correct_ms"] += correct
        turns.append(
            {
                "id": turn.get("id"),
                "start_ms": start,
                "end_ms": end,
                "expected": expected_role,
                "durations_ms": durations,
                "correct": math.isclose(correct, labelled, abs_tol=1e-6),
            }
        )
    return {
        "expected_turns": len(turns),
        "actual_segments": len(actual_segments),
        **totals,
        "role_accuracy": fraction(totals["correct_ms"], totals["labelled_ms"]),
        "role_coverage": fraction(totals["covered_ms"], totals["labelled_ms"]),
        "decision_coverage": fraction(totals["decisive_ms"], totals["labelled_ms"]),
        "decisive_accuracy": fraction(totals["correct_decisive_ms"], totals["decisive_ms"]),
        "turn_accuracy": fraction(sum(turn["correct"] for turn in turns), len(turns)),
        "per_role": {
            role: {**values, "accuracy": fraction(values["correct_ms"], values["labelled_ms"])}
            for role, values in per_role.items()
        },
        "turns": turns,
    }


def word_error_rate(reference: str, hypothesis: str) -> Record:
    """Case/punctuation-normalized word edit distance; empty references have no rate."""
    expected = re.findall(r"\w+(?:['’]\w+)*", reference.casefold().replace("’", "'"))
    actual = re.findall(r"\w+(?:['’]\w+)*", hypothesis.casefold().replace("’", "'"))
    previous = list(range(len(actual) + 1))
    for row, word in enumerate(expected, start=1):
        current = [row]
        for column, predicted in enumerate(actual, start=1):
            current.append(
                min(
                    current[column - 1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (word != predicted),
                )
            )
        previous = current
    errors = previous[-1]
    return {
        "errors": errors,
        "reference_words": len(expected),
        "hypothesis_words": len(actual),
        "rate": errors / len(expected) if expected else None,
    }


def score_identity(
    visible: list[Record], frames: list[Record], previous: dict[str, str], *, aligned: bool
) -> Record:
    mapping = dict(previous)
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    labelled: list[tuple[str, str | None]] = []
    counts: list[bool] = []
    seen: set[float] = set()
    duplicates = 0
    for frame in frames if aligned else []:
        if frame["source_ms"] in seen:
            duplicates += 1
            continue
        seen.add(frame["source_ms"])
        label = next(
            (v for v in visible if v["start_ms"] <= frame["source_ms"] < v["end_ms"]), None
        )
        if label is None:
            continue
        tracks = frame.get("tracks", [])
        counts.append(len(tracks) == label["face_count"])
        if label["face_count"] != 1 or label["visitor_id"] is None:
            continue
        person = tracks[0].get("person_id") if len(tracks) == 1 else None
        visitor = label["visitor_id"]
        labelled.append((visitor, person))
        if person:
            votes[visitor][person] += 1
    ambiguous = []
    for visitor, identities in votes.items():
        if visitor in mapping:
            continue
        best = identities.most_common()
        if (len(best) > 1 and best[0][1] == best[1][1]) or best[0][0] in mapping.values():
            ambiguous.append(visitor)
        else:
            mapping[visitor] = best[0][0]
    return {
        "scored": aligned,
        "duplicate_frame_responses": duplicates,
        "identity_map": mapping,
        "ambiguous_mappings": ambiguous,
        "face_count_accuracy": fraction(sum(counts), len(counts)),
        "association_coverage": fraction(sum(p is not None for _, p in labelled), len(labelled)),
        "frame_accuracy": fraction(
            sum(p is not None and mapping.get(v) == p for v, p in labelled), len(labelled)
        ),
        "missed_associations": sum(p is None for _, p in labelled),
        "wrong_associations": sum(
            p is not None and v in mapping and mapping[v] != p for v, p in labelled
        ),
        "duplicate_profiles": {v: list(c) for v, c in votes.items() if len(c) > 1},
    }


def score_evidence(facts: list[Record], segments: list[Record]) -> Record:
    indexed = {s["id"]: s for s in segments}
    checked = 0
    valid = 0
    invalid = []
    for fact in facts:
        for evidence in fact.get("evidence", []):
            checked += 1
            segment = indexed.get(evidence["segment_id"])
            if segment and evidence["quote"] and evidence["quote"] in segment["text"]:
                valid += 1
            else:
                invalid.append({"fact_id": fact["id"], **evidence})
    return {"resolvable_quotes": fraction(valid, checked), "invalid_references": invalid}


def score_memory(expected: list[Record], actual: list[Record], segments: list[Record]) -> Record:
    # State is part of the expected outcome: superseded/history/plans must not be
    # credited as established current facts.
    result = score_facts([f for f in expected if f.get("status", "accepted") == "accepted"], actual)

    def key(f: Record) -> tuple:
        return (*_fact_key(f), f.get("status", "accepted"))

    wanted = {
        key(f)
        for f in expected
        if f.get("present", True) and f.get("status", "accepted") != "accepted"
    }
    observed = {key(f) for f in actual}
    result["historical_state_coverage"] = fraction(len(wanted & observed), len(wanted))
    result["states"] = dict(Counter(f.get("status", "accepted") for f in actual))
    result["evidence"] = score_evidence(actual, segments)
    return result


def clock_time(samples: list[Record], source_ms: float) -> float | None:
    if len(samples) < 2:
        return None
    points = [(float(s["source_ms"]), float(s["performance_ms"])) for s in samples]
    if any(not math.isfinite(x) or not math.isfinite(y) for x, y in points):
        raise ValueError("Clock samples must be finite")
    if any(a >= c or b >= d for (a, b), (c, d) in zip(points, points[1:], strict=False)):
        raise ValueError("Clock samples must increase")
    if source_ms < points[0][0] or source_ms > points[-1][0]:
        return None
    index = min(bisect_right([p[0] for p in points], source_ms), len(points) - 1)
    left, right = points[index - 1], points[index]
    return left[1] + (source_ms - left[0]) * (right[1] - left[1]) / (right[0] - left[0])


def score_latency(facts: list[Record], transport: Record, segments: list[Record]) -> Record:
    measurements = []
    evidence = {s["id"]: s for s in segments}
    prior = set(transport.get("prior_fact_ids", []))
    observations = {o["fact_id"]: o for o in transport.get("fact_observations", [])}
    if transport.get("alignment_valid", False):
        for fact in facts:
            if fact["id"] in prior or fact["id"] not in observations:
                continue
            sources = [
                evidence[e["segment_id"]]
                for e in fact.get("evidence", [])
                if e["segment_id"] in evidence
            ]
            # Evidence from an earlier encounter cannot be aligned to this source clock.
            sources = [s for s in sources if s.get("current_encounter", False)]
            if not sources:
                continue
            speech_ms = max(s["end_ms"] for s in sources)
            speech_elapsed = clock_time(transport["clock_samples"], speech_ms)
            observation = observations[fact["id"]]
            if speech_elapsed is None or observation["performance_ms"] < speech_elapsed:
                continue
            measurements.append(
                {
                    "fact_id": fact["id"],
                    "speech_end_ms": speech_ms,
                    "latency_ms": observation["performance_ms"] - speech_elapsed,
                    "poll_uncertainty_ms": observation["poll_interval_ms"],
                }
            )
    return {
        "speech_to_saved": percentiles([m["latency_ms"] for m in measurements]),
        "measurements": measurements,
        "alignment_valid": transport.get("alignment_valid", False),
    }
