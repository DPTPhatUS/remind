"""Numeric helpers shared by benchmark reports."""

import math
from collections.abc import Sequence

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
