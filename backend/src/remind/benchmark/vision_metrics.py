"""Frame-throughput and labelled face-identification measurements."""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np


def summarize(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
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


def identification_metrics(
    truth: Sequence[str | None], predictions: Sequence[str | None]
) -> dict[str, Any]:
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
