# Benchmarking Remind

There are four benchmark paths. All use production processing code and isolated
storage. Expected labels are used for scoring; they are never supplied to models,
except transcript text and roles in the conversation component benchmark.

| Command | Input → output | What it measures |
| --- | --- | --- |
| `audio` | Enrollment + audio → timestamped roles | Decoding, automatic transcription/diarization, local user/visitor/uncertain decisions |
| `conversation` | Role-labelled text → saved facts | Contextual extraction, verification, evidence validation, consolidation |
| `face` | Ordered video encounters → face associations | Detection, tracking, automatic enrollment, recognition on return |
| `video` | Enrollment + video/audio → saved visitor facts | The complete backend pipeline, including capture-time face gating |

## Run

Install dependencies and verified local models as described in the root README.
Run from `backend/`:

```bash
uv sync --extra speaker
uv run --extra speaker python -m remind.cli benchmark audio /path/to/audio.json --output .local/benchmark-results/audio --cloud
uv run --extra speaker python -m remind.cli benchmark conversation /path/to/conversation.json --output .local/benchmark-results/conversation --cloud
uv run --extra speaker python -m remind.cli benchmark face /path/to/face.json --output .local/benchmark-results/face
uv run --extra speaker python -m remind.cli benchmark video /path/to/video.json --output .local/benchmark-results/video --cloud
```

Each output directory must be new. `--cloud` explicitly enables paid requests
using the configured transcription or text provider. The face command uses only
local models and disables cloud calls in its isolated backend. Conversation needs
no audio, face models, or voice reference. The application's active store is
never reused.

Examples live in [examples/](examples/). The text example is a scripted component
input; media examples have placeholder paths and hashes. Actual retained inputs
on this workstation live in `backend/.local/benchmark-inputs/`, outside Git.
That directory contains `audio.json`, `conversation.json`, `face.json`, and
`video.json`, plus short `conversation-smoke.json` and `face-smoke.json` inputs.
`video-fixture-smoke.json` combines retained face and scripted-audio inputs to
exercise the complete backend chain; it is explicitly a synthetic integration case.
See [FOOTAGE.md](FOOTAGE.md) for public-source attribution and annotation limits.

## Inputs and execution

All manifests contain a title, annotation notes, limitations, and cases. Media
also requires source provenance, SHA-256, original source interval, and any
preprocessing commands. Paths resolve relative to the manifest. Record labels
before inference; preserve ambiguous and missing scenarios explicitly.

Audio cases contain optional enrollment and ordered recordings with labelled
turns. Enrollment follows the current application contract: three to five
separate samples, 3–20 seconds each. Empty enrollment explicitly tests missing
references. Enrollment passages cannot overlap scored passages. Samples can be
reused across independent cases. Preparation checks source timestamps, preserves
small measured A/V offsets, reports edge padding/trimming, and rejects genuine
discontinuities. Audio becomes mono 16 kHz WAV, split into eight-second windows
plus a final partial clip. Audio processing runs sequentially without playback
sleeps and stops before extraction.

Conversation cases contain dated encounters and ordered transcript batches.
Turn timestamps are relative to the encounter and must fit within their batch.
Encounter dates require timezones. Each case has one fixture visitor and an
independent SQLite store. Context accumulates across batches; existing facts
remain available across encounters. Roles are trusted component inputs. The
benchmark calls the same learning and transactional claim-writing functions as
live jobs, without fabricated voice references. Expected facts describe the
final saved state of the case.

Face and video cases contain ordered encounters. Visibility labels specify face
count and, where exactly one face is unambiguous, the expected visitor identity.
The runner starts an isolated backend, sends source-timed JPEG frames through
the normal live WebSocket, and uses automatic enrollment. It never supplies a
face gallery or expected identities to the backend. Face mode accepts video-only
files. Video mode additionally enrolls through the normal voice API and uploads
clean audio through the normal clip API.

Visual replay runs once at normal speed. Frames over 100 ms late are counted and
skipped; the production queue can also replace frames. Audio uploads run
independently and use the same source clock. There are no extra benchmark
retries. Video preserves production job retries, then waits up to ten minutes
for outstanding work. Upload failures and unfinished/failed jobs remain visible.
Face/video encounters share a case store, allowing returning-face recognition.
The benchmark does not automate restart, reminder recall, or forgetting.

## Results

Each run produces `report.json`, `report.md`, frozen/resolved manifests, and
case artifacts. Reports record effective settings without API keys, model/code
identifiers, source hashes, execution failures, raw observations, and timings.
Audio retains transcripts, scores and clip timings; conversation retains model
proposals, verification assessments, saved facts and evidence; visual runs retain
face responses, uploads, source-clock samples and job observations. Face templates
and voice embeddings are not exported. Isolated run databases remain local.

Scores separate role correctness, confident errors, uncertainty, missed speech,
face counts/associations, duplicate profiles, useful-fact coverage, wrong subjects,
required absences, historical state, evidence references, and latency. Exact fact
matching normalizes case and whitespace. Unmatched paraphrases require manual
evidence review and are not automatically labelled unsupported. Profile names
cannot establish face identity. Latency includes polling uncertainty and excludes
invalid clock alignment. Empty denominators are reported as unmeasured.

Execution completion is independent of accuracy. There is no minimum dataset
size, fixed accuracy acceptance score, browser benchmark, or throughput mode.
Report the number of independent people/conversations and disclose repeated
footage, provisional annotations, synthetic inputs, and missing coverage.
Recorded-input success does not establish physical capture quality, browser UI
behavior, or accuracy for people with memory impairments.

## Development verification

```bash
cd backend
uv run --extra speaker pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/remind
```

Frontend tests remain ordinary application correctness checks:

```bash
cd frontend
npm test
npm run build
npm run lint
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

The browser suite requires the existing single-face fixture at
`backend/.local/e2e/camera.y4m` and installed models. Playwright starts its own
backend with an isolated temporary store. `REMIND_E2E_DATA_DIR` can select an
explicit disposable directory. Browser tests cover helper setup, profiles,
correction, returning reminders and forgetting; they are separate from benchmark
accuracy measurements.

## Cleanup

The four paths replace voice smoke, synthetic fixture generation, audio-to-memory
replay, gallery-based face replay, full-session replay and browser-trace scoring.
Their old entry points, formats, tests and dependencies on each other were removed.
Browser replay/capture harnesses and performance trace export were removed.
Useful production guard tests and shared scoring/media/transport tests remain.
Historical reports, run stores, prepared clips, archived source copies and browser
investigation tools were deleted. Original media, source annotations/provenance,
application test inputs, models, licenses, credentials and active memories remain.
