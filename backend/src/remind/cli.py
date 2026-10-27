import argparse
import importlib.util
import json
import time
from pathlib import Path

from remind.config import Settings
from remind.vision.models import ModelRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="Remind local runtime tools")
    commands = parser.add_subparsers(dest="command", required=True)
    models = commands.add_parser("models")
    models.add_argument("action", choices=["install"])
    commands.add_parser("doctor")
    bench = commands.add_parser("benchmark", help="Replay recorded video through face recognition")
    bench.add_argument("manifest", type=Path)
    bench.add_argument("--output", type=Path, required=True)
    bench.add_argument("--mode", choices=["realtime", "throughput"], default="realtime")
    evaluate = commands.add_parser(
        "evaluate-trace", help="Score an annotated browser-session trace"
    )
    evaluate.add_argument("trace", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    registry = ModelRegistry(settings.data_dir / "models")
    if args.command == "models":
        registry.install()
        print("Verified model installation complete.")
    elif args.command == "doctor":
        model_status: dict[str, str] = {}
        result = {
            "vision_device": "cpu",
            "voice_device": "cpu",
            "cloud_key_configured": bool(settings.openai_api_key),
            "models": model_status,
        }
        for name in registry.models:
            try:
                model_status[name] = str(registry.verify(name))
            except (FileNotFoundError, ValueError) as exc:
                model_status[name] = str(exc)
        if importlib.util.find_spec("torch"):
            import torch

            result["torch"] = torch.__version__
            result["cuda_available"] = torch.cuda.is_available()
        from remind.audio.speaker import UserVoiceVerifier

        result["voice"] = UserVoiceVerifier(settings, registry).readiness()
        result["thresholds_calibrated"] = False
        print(json.dumps(result, indent=2))
    elif args.command == "evaluate-trace":
        from remind.benchmark.report import write_report
        from remind.benchmark.trace_metrics import evaluate_trace

        trace = json.loads(args.trace.read_text())
        result = evaluate_trace(trace)
        result["events"] = trace.get("frames", [])
        write_report(result, args.output)
        print(json.dumps(result, indent=2))
    else:
        from remind.benchmark.report import write_report
        from remind.benchmark.video_replay import replay_video

        started = time.monotonic()
        result = replay_video(args.manifest, settings, args.mode)
        result["wall_seconds"] = time.monotonic() - started
        write_report(result, args.output)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
