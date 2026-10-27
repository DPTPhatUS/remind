"""Score a browser timing trace and its independently labelled outcomes."""

import math
from typing import Any

from remind.benchmark.metrics import fraction, percentiles
from remind.benchmark.vision_metrics import identification_metrics, summarize


def evaluate_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Score browser timing plus independently adjudicated encounter/fact outcomes.

    Outcomes are per independent encounter/fact, never per neighboring video frame.
    This does not manufacture annotations or claim full acceptance from a short trace.
    """
    frames = trace.get("frames", [])
    clocks = {e.get("clock") for e in frames}
    if len(clocks) > 1 or (frames and None in clocks):
        raise ValueError("All frame times must use one declared browser clock")
    frames = list(
        {
            (e.get("generation"), e["sequence"]): e
            for e in frames
            if not e.get("interpolated", False)
        }.values()
    )
    ages = [e["painted_ms"] - e["capture_ms"] for e in frames if "painted_ms" in e]
    if any(not math.isfinite(v) or v < 0 for v in ages):
        raise ValueError("Invalid clock difference in capture-to-paint times")
    identities = trace.get("identities", [])
    known = [e for e in identities if e["expected"] is not None]
    facts = trace.get("facts", [])
    correct_facts = [f for f in facts if f["supported"] and f["subject_correct"]]
    eligible_facts = trace.get("eligible_facts", 0)
    enrollment = trace.get("enrollments", [])
    recall = trace.get("recalls", [])
    return {
        "vision": summarize(frames),
        "latency": percentiles(ages),
        "identification": identification_metrics(
            [e["expected"] for e in identities], [e["predicted"] for e in identities]
        ),
        "recognition_coverage": fraction(
            sum(
                e["expected"] == e["predicted"] and e.get("latency_ms", math.inf) <= 2000
                for e in known
            ),
            len(known),
        ),
        "identity_latency": percentiles(
            [
                e["latency_ms"]
                for e in known
                if e["predicted"] == e["expected"] and "latency_ms" in e
            ]
        ),
        "enrollment": fraction(sum(bool(e["correct"]) for e in enrollment), len(enrollment)),
        "duplicate_enrollments": fraction(
            sum(bool(e["duplicate"]) for e in enrollment), len(enrollment)
        ),
        "fact_precision": fraction(len(correct_facts), len(facts)),
        "subject_precision": fraction(sum(bool(f["subject_correct"]) for f in facts), len(facts)),
        "fact_coverage": fraction(
            len(
                {
                    f["expected_fact_id"]
                    for f in correct_facts
                    if f.get("expected_fact_id") is not None
                }
            ),
            eligible_facts,
        ),
        "memory_latency": percentiles([f["latency_ms"] for f in facts if "latency_ms" in f]),
        "recall": fraction(sum(bool(e["correct"]) for e in recall), len(recall)),
        "named_switches": trace.get("named_switches"),
        "acceptance_complete": False,
        "note": "Review scenario coverage, held-out splits, independence, duration and all gates "
        "in docs/testing/realtime-memory-evaluation.md; missing labels are not success.",
    }
