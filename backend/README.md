# Remind backend

FastAPI, SQLite, local YuNet/SFace face recognition, and local CPU SpeechBrain
ECAPA-TDNN user-voice verification. OpenAI handles diarized English transcription,
contextual extraction, and a separate evidence-verification pass.

See the [root README](../README.md) for setup and the one-on-one assumptions.
Use `uv sync --extra speaker` and retain `--extra speaker` in uv runtime commands.
The model installer verifies pinned assets. Runtime data lives under `.local/`;
configuration is in `.env` (see [.env.example](.env.example)).

Vision and conversation work use separate executors. The latest-only vision queue
prevents stale overlays; conversation jobs preserve capture-time visitor and voice
reference versions. Uploads are accepted before identification. Audio jobs save
transcripts once; learning jobs associate complete turns with encounters. A single
candidate supports automatic recognition/enrollment, and an encounter allows five
seconds of temporary absence. Competing/multiple faces pause learning.

Runtime owns the cloud provider, shared voice verifier and executors. Voice setup
and the memory worker use the same single-thread audio executor. The worker uses
supplied dependencies; Runtime stops background tasks before closing resources.

Leases, transactional writes, and idempotent windows protect
retries and restarts. Source transcripts and structured evidence support correction
and forgetting. No video is decoded for voice recognition.

Startup creates the current schema and recovers unfinished work. Normal restarts
preserve memories. Older schemas are not supported; there is no migration layer.

[API contract](docs/API.md) · [Attribution and cleanup](docs/ATTRIBUTION.md) · [Refactor record](docs/REFACTOR.md) · [Evaluation](../docs/testing/realtime-memory-evaluation.md)
