"""Associate whole speech turns with capture-time encounter intervals."""

from remind.database import Record


def associate_turn(turn: Record, timeline: list[Record], *, final: bool) -> Record:
    start, end = turn["start_ms"], turn["end_ms"]
    points = sorted(timeline, key=lambda point: point["ms"])
    before = [i for i, point in enumerate(points) if point["ms"] <= start]
    rejected = {
        "status": "unattributed",
        "reason": "stale_observations",
        "visitor_id": None,
        "encounter_id": None,
    }
    if not before or end <= start:
        return rejected
    index = before[-1]
    cursor = start
    identity = None
    bases = set()
    version = None
    while cursor < end:
        point = points[index]
        next_ms = points[index + 1]["ms"] if index + 1 < len(points) else end
        until = min(end, next_ms, point.get("eligible_until", end))
        if until <= cursor or until - point["ms"] > 500:
            return rejected
        if not point.get("eligible"):
            pending = point.get("reason") == "initial_candidate" and not final
            return {
                **rejected,
                "status": "pending" if pending else "unattributed",
                "reason": point.get("reason", "ambiguity"),
            }
        current = (point.get("encounter_id"), point.get("visitor_id"))
        if not all(current) or (identity is not None and identity != current):
            return {**rejected, "reason": "encounter_boundary"}
        if version is not None and version != point["person_version"]:
            return {**rejected, "reason": "person_changed"}
        identity = current
        version = point["person_version"]
        bases.add(point["reason"])
        cursor = until
        if cursor < end:
            if until < min(end, next_ms):
                return {**rejected, "reason": "absence_expired"}
            index += 1
    assert identity is not None
    return {
        "status": "attributed",
        "reason": "absence_allowance"
        if "absence_allowance" in bases
        else "initial_candidate_backfill"
        if "initial_candidate_backfill" in bases
        else "direct_confirmation",
        "encounter_id": identity[0],
        "visitor_id": identity[1],
        "person_version": version,
    }


def eligible_source(source: Record, person_id: str, encounter_id: str) -> bool:
    association = source.get("association", {})
    return (
        association.get("status") == "attributed"
        and association.get("visitor_id") == person_id
        and association.get("encounter_id") == encounter_id
    )
