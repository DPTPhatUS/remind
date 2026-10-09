# Remind

A local, single-patient memory assistant. Open the live camera view, meet someone,
and return later to see their remembered information beside their face.

## Run

Python 3.12+ and Node.js are required. In separate terminals:

```bash
cd backend
uv sync --extra speaker
uv run --extra speaker python -m remind.cli models install
# Put OPENAI_API_KEY (or REMIND_OPENAI_API_KEY) in backend/.env.
uv run --extra speaker uvicorn remind.app:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open <http://127.0.0.1:5173> and choose **Start camera**. Allow camera and
microphone access. **Stop camera** releases both devices and flushes the last
conversation clip. Live and People are the only app sections.

The model installer downloads pinned YuNet, SFace and Light-ASD weights and
verifies their SHA-256 hashes. No face-service container, PostgreSQL, Redis or
vector database is required. A fresh SQLite database is created automatically
at `backend/.local/remind.sqlite3`. Existing legacy databases are not migrated
or deleted. Keep the backend on localhost; remote hosting is outside this version.

## Memory behavior

- A stable, clear, sufficiently close unfamiliar face can be enrolled after
  two seconds and five usable observations. Names are optional.
- Returning faces need repeated agreement and separation from the next-best
  person. Uncertain identity produces no named reminder.
- Conversations are captured in bounded synchronized audio/video clips. Audio
  goes to OpenAI for speaker-labeled transcription; local Light-ASD supplies
  face/speaker evidence. Structured fact extraction receives the transcript
  and supported subject mapping. It does not choose face identities.
- Unassigned speech can contribute to an encounter summary but cannot fill a
  person's name, age or relationship. Missing speaker models degrade to that
  behavior explicitly. No age or relationship is estimated from appearance.
  Automatic profile fields currently require direct English self-statements
  such as “My name is Anna” and “I am your daughter”; richer details remain in
  the encounter summary when their subject cannot be supported.
- The card shows the previous completed encounter, excluding the current one.
- People lets you inspect sources, correct fields and forget someone. Forget
  also removes related shared-conversation text and invalidates pending jobs.

The cloud account is the existing OpenAI API service. Face templates remain
local. Audio and transcript text leave the device when cloud processing is on.
Temporary clips are local, capped at 1 GiB and expired after 24 hours (both
configurable). Failed uploads pause capture and retain one clip in the current
tab for retry or download. Processing failures can be retried from the live view. Stop
recording whenever you do not want an interaction recorded.

## Current validation limits

This is an engineering prototype. Recognition and speaker thresholds are
uncalibrated defaults. Unit tests and repeated-image speed tests do not establish
real-world identification or personal-fact accuracy. The full 30-minute,
1–3-person, ≥10 processed-fps acceptance run and labeled encounter evaluation
must be recorded separately. [Measured results](docs/testing/reports/2026-10-09-implementation.md)
include a short 25 fps browser smoke with an 85 ms p95 display-time bound. See the [evaluation strategy](docs/testing/realtime-memory-evaluation.md)
and [execution record](docs/superpowers/execution/progress.md).

The initial runtime uses CPU OpenCV and an optional CPU PyTorch wheel. Your
RTX 2050 is available, but using CUDA for speaker inference requires a compatible
CUDA PyTorch installation and `REMIND_SPEAKER_DEVICE=cuda`. It is not required
for local face recognition. The normal OpenCV wheel is CPU-only.

## Verify

```bash
cd backend
uv run --extra speaker pytest
uv run ruff check .
uv run mypy src/remind
uv run --extra speaker python -m remind.cli doctor
```

```bash
cd frontend
npm test
npm run build
npm run lint
```

Browser test instructions and recorded-media benchmarks are in
[benchmarks/README.md](benchmarks/README.md). The approved [design](docs/superpowers/specs/2026-10-08-realtime-memory-design.md)
and [plan](docs/superpowers/plans/2026-10-08-realtime-memory.md) explain the targets.
