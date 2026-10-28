"""One report format for all four benchmark commands."""

import json
from pathlib import Path
from typing import Any


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def metric_row(label: str, metric: dict) -> str:
    rate = metric.get("rate")
    value = (
        "Not measured"
        if rate is None
        else (f"{metric['numerator']:.1f}/{metric['denominator']:.1f} ({rate:.1%})")
    )
    return f"| {label} | {value} |"


def write_report(result: dict, output: Path) -> None:
    write_json(result, output / "report.json")
    lines = [
        f"# Remind {result['kind']} benchmark",
        "",
        f"Execution: {result['status']}",
        "",
        result["title"],
        "",
        "Execution status describes completion, not model accuracy.",
        "",
    ]
    for case in result["cases"]:
        lines += [f"## {case['id']}", "", f"Execution: {case['status']}", ""]
        for error in case.get("errors", []):
            lines += [f"- Error: {error}"]
        for outcome in case.get("outcomes", []):
            lines += ["", f"### {outcome['id']}", "", "| Measurement | Result |", "| --- | --- |"]

            scores = outcome.get("scores", {})
            if "roles" in scores:
                lines.append(
                    metric_row(
                        "Role correctness (labelled duration)", scores["roles"]["role_accuracy"]
                    )
                )
                lines.append(
                    metric_row("Decisive role coverage", scores["roles"]["decision_coverage"])
                )
                lines.append(
                    f"| Confident role errors | {scores['roles']['wrong_role_ms']:.1f} ms |"
                )
                lines.append(f"| Uncertain speech | {scores['roles']['uncertain_ms']:.1f} ms |")
                lines.append(f"| Missed speech | {scores['roles']['missed_ms']:.1f} ms |")
            if "identity" in scores:
                lines.append(metric_row("Face count", scores["identity"]["face_count_accuracy"]))
                lines.append(metric_row("Face association", scores["identity"]["frame_accuracy"]))
                lines.append(
                    f"| Missed face associations | {scores['identity']['missed_associations']} |"
                )
            if "memory" in scores:
                memory = scores["memory"]
                lines.append(metric_row("Useful fact coverage", memory["fact_coverage"]))
                lines.append(metric_row("Raw exact matching", memory["raw_exact_precision"]))
                lines.append(metric_row("Required absence checks", memory["required_absence"]))
                lines.append(
                    metric_row("Historical state coverage", memory["historical_state_coverage"])
                )
                lines.append(f"| Wrong subjects | {len(memory['wrong_subject_additions'])} |")
                lines.append(
                    "| Unmatched additions needing review | "
                    f"{len(memory['unmatched_additions_require_review'])} |"
                )
            if "latency" in scores:
                latency = scores["latency"]["speech_to_saved"]
                value = (
                    f"p50 {latency['p50_ms']:.1f} ms; p95 {latency['p95_ms']:.1f} ms"
                    if latency["count"]
                    else "Not measured"
                )
                lines.append(
                    f"| Speech to saved fact ({latency['count']} measurements) | {value} |"
                )
            transport = outcome.get("transport")
            if transport is not None:
                uploads = transport.get("uploads", [])
                jobs = sum(bool(u.get("receipt", {}).get("clip_id")) for u in uploads)
                lines.append(f"| Frames sent | {transport.get('frames_sent', 0)} |")
                lines.append(f"| Frames skipped late | {transport.get('frames_skipped_late', 0)} |")
                if result["kind"] == "video":
                    lines.append(f"| Queued audio jobs | {jobs} |")
                    lines.append(f"| Unattributed turns | {outcome.get('unattributed_turns', 0)} |")
                    lines.append(f"| Transcribed turns | {len(outcome.get('segments', []))} |")
                    for reason, count in outcome.get("association", {}).items():
                        lines.append(f"| Association: {reason} | {count} |")
                    if uploads and not jobs:
                        lines += [
                            "",
                            "No audio jobs were queued. Voice classification and "
                            "extraction correctness were not measured.",
                        ]
            for missing in scores.get("memory", {}).get("missing_expected", []):
                lines += [
                    "",
                    f"- Missed expected fact: {missing['subject']} / "
                    f"{missing['predicate']} / {missing['value']}",
                ]
    lines += ["", "## Interpretation", "", result["annotation_notes"], ""]
    lines += [f"- {item}" for item in result["limitations"]]
    lines += [
        "- Unmatched paraphrases require evidence review; exact wording is not a semantic judge.",
        "- Empty output and small fixture runs cannot establish real-world accuracy.",
        "- Full raw observations and per-stage timings are in report.json and case artifacts.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
