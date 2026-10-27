"""JSON output for evaluations and event-report bundles for video and traces."""

import json
from pathlib import Path
from typing import Any


def write_json(result: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def write_report(result: dict[str, Any], output: str | Path) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    events = result.get("events", [])
    summary = {key: value for key, value in result.items() if key != "events"}
    summary_json = json.dumps(summary, indent=2)
    write_json(summary, output / "report.json")
    (output / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (output / "report.md").write_text(
        "# Remind benchmark\n\n"
        "Full accuracy/performance acceptance is not established by this report alone.\n\n"
        "```json\n" + summary_json + "\n```\n"
    )
