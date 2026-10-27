import json

import pytest

from remind.benchmark.metrics import fraction, percentiles
from remind.benchmark.report import write_report
from remind.benchmark.trace_metrics import evaluate_trace
from remind.benchmark.vision_metrics import summarize


def test_duplicate_frames_and_empty_runs_cannot_pass():
    assert summarize([])["fps_gate_pass"] is False
    events = [{"sequence": i // 2, "capture_ms": i * 100, "processing_ms": 20} for i in range(200)]
    report = summarize(events)
    assert report["unique_frames"] == 100
    assert report["fps_gate_pass"] is False


def test_eligible_ten_second_windows_have_explicit_denominators():
    events = [{"sequence": i, "capture_ms": i * 50, "processing_ms": 20} for i in range(600)]
    report = summarize(events)
    assert report["complete_windows"] == 2
    assert report["passing_windows"] == 2
    assert report["processing_p95_ms"] == 20
    assert report["acceptance_complete"] is False


def test_trace_metrics_require_labels_and_consistent_clocks():
    assert evaluate_trace({"frames": []})["acceptance_complete"] is False
    trace = {
        "frames": [
            {
                "sequence": 1,
                "capture_ms": 0,
                "processing_ms": 10,
                "painted_ms": 50,
                "clock": "browser-1",
            }
        ],
        "facts": [],
    }
    report = evaluate_trace(trace)
    assert report["fact_precision"]["denominator"] == 0
    assert report["fact_precision"]["rate"] is None
    assert report["latency"]["p95_ms"] == 50
    with pytest.raises(ValueError, match="clock"):
        evaluate_trace(
            {
                "frames": [
                    {
                        "sequence": 1,
                        "capture_ms": 100,
                        "painted_ms": 50,
                        "processing_ms": 10,
                        "clock": "browser-1",
                    }
                ]
            }
        )


def test_trace_coverage_cannot_pass_by_abstaining():
    report = evaluate_trace(
        {
            "frames": [],
            "eligible_facts": 10,
            "facts": [],
            "identities": [{"expected": "anna", "predicted": None}],
        }
    )
    assert report["fact_coverage"]["rate"] == 0
    assert report["recognition_coverage"]["rate"] == 0
    assert report["acceptance_complete"] is False


@pytest.mark.parametrize("latency", [-1, float("nan"), float("inf")])
def test_latency_reports_reject_invalid_measurements(latency):
    with pytest.raises(ValueError, match="finite and non-negative"):
        percentiles([latency])


def test_fraction_supports_duration_sums_and_preserves_missing_denominators():
    assert fraction(12.5, 25) == {"numerator": 12.5, "denominator": 25, "rate": 0.5}
    assert fraction(0, 0) == {"numerator": 0, "denominator": 0, "rate": None}
    assert fraction(0.1 + 0.2, 0.3) == {
        "numerator": 0.3,
        "denominator": 0.3,
        "rate": 1,
    }
    assert fraction(-1e-12, 5)["rate"] == 0


@pytest.mark.parametrize(
    "numerator,denominator",
    [
        (2, 1),
        (-1, 5),
        (1, 0),
        (0, -1),
        (1.01, 1.0),
        (-0.01, 1.0),
        (float("nan"), 1),
        (1, float("inf")),
        (10**12 + 1, 10**12),
        (10**12 + 1.0, 10**12),
        (1e-12, 0),
    ],
)
def test_fraction_rejects_invalid_inputs_instead_of_clamping_real_errors(numerator, denominator):
    with pytest.raises(ValueError, match="Invalid metric"):
        fraction(numerator, denominator)


def test_writing_report_preserves_original_result_and_separates_events(tmp_path):
    result = {"mode": "realtime", "events": [{"sequence": 1, "processing_ms": 10}]}
    write_report(result, tmp_path)
    assert result["events"] == [{"sequence": 1, "processing_ms": 10}]
    assert json.loads((tmp_path / "report.json").read_text()) == {"mode": "realtime"}
    assert json.loads((tmp_path / "events.jsonl").read_text()) == result["events"][0]
