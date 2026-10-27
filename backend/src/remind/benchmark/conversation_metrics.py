"""Score labelled audio runs without using a model to judge its own output.

Fact matching ignores case and whitespace only. The expected list must describe
all supported claims for a closed-world run; unmatched paraphrases need human
review. An expected claim with ``present=False`` is a required absence case.
"""

import math
import re
from collections.abc import Sequence
from typing import Any

from remind.benchmark.metrics import fraction

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
        "fact_precision": fraction(len(matched), len(saved)),
        "fact_coverage": fraction(len(matched), len(positives)),
        "required_absence": fraction(satisfied_absences, len(negatives)),
        "matched": matched,
        "missing_expected": missing,
        "unsupported_additions": unsupported,
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
