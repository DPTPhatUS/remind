import json
from pathlib import Path


def write_report(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    events = result.pop("events", [])
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    (output / "report.md").write_text(
        "# Remind benchmark\n\n"
        "Full accuracy/performance acceptance is not established by this report alone.\n\n"
        "```json\n" + json.dumps(result, indent=2) + "\n```\n"
    )
