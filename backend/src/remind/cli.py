import argparse
import importlib.util
import json
from pathlib import Path

from remind.config import Settings
from remind.vision.models import ModelRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="Remind local runtime tools")
    commands = parser.add_subparsers(dest="command", required=True)
    models = commands.add_parser("models")
    models.add_argument("action", choices=["install"])
    commands.add_parser("doctor")
    benchmark = commands.add_parser("benchmark", help="Evaluate a production processing path")
    paths = benchmark.add_subparsers(dest="path", required=True)
    for name in ("audio", "conversation", "face", "video"):
        command = paths.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument("--output", type=Path, required=True)
        if name != "face":
            command.add_argument("--cloud", action="store_true", help="Enable paid provider calls")
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
    else:
        from remind.benchmark.runner import run

        result = run(args.path, args.manifest, args.output, getattr(args, "cloud", False), settings)
        print(json.dumps({"status": result["status"], "report": str(args.output / "report.md")}))
        if result["status"] != "complete":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
