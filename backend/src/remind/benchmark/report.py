import json
from pathlib import Path
from typing import Any


def write_report(result: dict[str, Any], output: str | Path) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    events = result.get("events", [])
    summary = {key: value for key, value in result.items() if key != "events"}
    summary_json = json.dumps(summary, indent=2)
    (output / "report.json").write_text(summary_json + "\n")
    (output / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (output / "report.md").write_text(
        "# Remind benchmark\n\n"
        "Full accuracy/performance acceptance is not established by this report alone.\n\n"
        "```json\n" + summary_json + "\n```\n"
    )
