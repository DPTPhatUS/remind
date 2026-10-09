import math

import numpy as np


def summarize(events):
    unique = {
        (e.get("generation"), e["sequence"]): e for e in events if not e.get("interpolated", False)
    }
    ordered = sorted(unique.values(), key=lambda e: e["capture_ms"])
    if not ordered:
        return {
            "unique_frames": 0,
            "fps_gate_pass": False,
            "acceptance_complete": False,
            "complete_windows": 0,
            "passing_windows": 0,
        }
    start, end = ordered[0]["capture_ms"], ordered[-1]["capture_ms"]
    windows = int((end - start) // 10000)
    counts = [
        sum(start + i * 10000 <= e["capture_ms"] < start + (i + 1) * 10000 for e in ordered)
        for i in range(windows)
    ]
    passing = sum(count >= 100 for count in counts)
    return {
        "unique_frames": len(ordered),
        "complete_windows": windows,
        "passing_windows": passing,
        "fps_gate_pass": windows > 0 and passing / windows >= 0.95,
        "processing_p95_ms": float(np.percentile([e["processing_ms"] for e in ordered], 95)),
        "acceptance_complete": False,
        "note": (
            "Component timings only. Browser latency, identity/fact accuracy "
            "and 30-minute acceptance require separate labeled runs."
        ),
    }


def identification_metrics(truth, predictions):
    known = [(a, b) for a, b in zip(truth, predictions, strict=True) if a is not None]
    unknown = [b for a, b in zip(truth, predictions, strict=True) if a is None]
    return {
        "known_trials": len(known),
        "correct_known": sum(a == b for a, b in known),
        "wrong_known": sum(b is not None and a != b for a, b in known),
        "unknown_trials": len(unknown),
        "false_known": sum(b is not None for b in unknown),
        "zero_error_upper_95": (1 - math.pow(0.05, 1 / len(unknown)))
        if unknown and all(b is None for b in unknown)
        else None,
    }


def fraction(numerator, denominator):
    if not 0 <= numerator <= denominator:
        raise ValueError("Invalid metric numerator/denominator")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def percentiles(values):
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None, "max_ms": None}
    return {
        "count": len(values),
        "p50_ms": float(np.percentile(values, 50)),
        "p95_ms": float(np.percentile(values, 95)),
        "p99_ms": float(np.percentile(values, 99)),
        "max_ms": max(values),
    }


def evaluate_trace(trace):
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
