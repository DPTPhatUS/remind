# Benchmarking Remind

Run everything on an isolated data directory. Keep participant media and labels
outside Git. See [the evaluation protocol](../docs/testing/realtime-memory-evaluation.md)
for fixture scope, metrics, and later staged-conversation evaluation.
The included example manifest contains placeholders, not a dataset.

## Logic and browser runners

```bash
cd backend
uv run --extra speaker pytest -q
```

`test_memory_loop.py` injects detections, transcription, user/visitor roles and semantic verification,
then runs enrollment → extraction → durable write → database close/reopen →
recognition → previous-encounter recall. Other tests cover corrections,
forgetting, stale workers, ambiguous matches, timestamps and job retries.
These are logic tests, not model accuracy results.

For the browser test, create a **disposable** store at `backend/.local/e2e`,
place verified model weights in its `models` directory (or symlink `../models`),
and provide a single-face Y4M file at `backend/.local/e2e/camera.y4m`.
Use a consenting test participant or a public test fixture. For a local video:

```bash
ffmpeg -i consented-test.mp4 -t 8 -vf scale=640:480 -r 25 -pix_fmt yuv420p camera.y4m
```

Start the backend with `REMIND_DATA_DIR=.local/e2e REMIND_OPENAI_API_KEY=''`
and start Vite as documented in the root README. Then:

```bash
cd frontend
npx playwright install chromium
npx playwright test --workers=1
# If bundled Chromium is unavailable but Chrome is installed:
# PLAYWRIGHT_CHANNEL=chrome npx playwright test --workers=1
```

The browser test uses a fake camera and real face inference, corrects a profile,
stops/restarts capture and verifies returning-person recall. **It deletes all
people in the server it tests. Never point it at a patient store.** Cloud calls
are disabled in this test. Screenshots go to `/tmp/remind-*.png`.

## Conversation fixtures and voice smoke

`e2e/one-on-one.spec.ts` exercises the full helper setup and rich-profile UI with
REST/WebSocket fixtures and real browser recording. It needs Vite, but no cloud
key. It establishes UI behavior, not neural or semantic accuracy. The real-camera
suite separately uses the disposable backend and verified face models.

The local ECAPA smoke uses pinned public SpeechBrain utterances. Enrollment has
three distinct utterances; verification uses separate same-user and other-speaker
utterances. Nothing is uploaded to OpenAI:

```bash
cd backend
uv run --extra speaker python -m remind.audio.smoke --download --output /tmp/remind-voice-smoke.json
```

The report separates correct assignments, abstentions, wrong assignments, model
revision, enrollment inputs and per-utterance inference timing. Four clean public
utterances do not establish real-world Remind accuracy or calibrate thresholds.

## Recorded video runner

Copy `manifest.example.json` beside your private media. Replace its SHA-256
(`sha256sum video.mp4`), gallery paths and labels. Paths are relative to the
manifest. Gallery images must contain exactly one usable face and come from a
separate enrollment session. A `null` frame label means an unknown person; an
omitted frame is unlabeled. This component runner supports single-face identity
labels; multi-person identity/fact outcomes belong in the adjudicated trace.

```bash
cd backend
uv run --extra speaker python -m remind.cli benchmark /path/to/manifest.json --output .local/reports/realtime --mode realtime
uv run --extra speaker python -m remind.cli benchmark /path/to/manifest.json --output .local/reports/throughput --mode throughput
```

Recorded-rate replay drops overdue frames. Throughput mode processes every
frame without real-time pacing. Reports include real model hashes, threshold,
margin, thread count, OpenCV version, frame counts and p95 processing time.
Outputs are `report.json`, `events.jsonl`, and `report.md`. A component replay
cannot establish browser latency, audio attribution, or 30-minute acceptance.
Neighboring video frames do not count as independent identity trials.

## Full-session timing and labeled outcomes

Start the real camera and use **Performance and memory status → Download
performance trace** after the run. This exports up to 100,000 fresh result
records with capture, receipt and a two-animation-frame paint-time upper bound,
all on the browser performance clock. A new camera session starts a new trace.
Run for at least 30 minutes at 1–3 faces, with the memory worker active. Record
power mode, CPU/GPU/RAM/thermal readings and network/provider costs separately.

```bash
cd backend
uv run python -m remind.cli evaluate-trace /path/to/remind-performance.json --output .local/reports/browser
```

For accuracy, independently annotate the same trace with these optional arrays:

```json
{
  "eligible_facts": 1,
  "identities": [{"expected":"person-001","predicted":"person-001","latency_ms":600}],
  "enrollments": [{"correct":true,"duplicate":false}],
  "facts": [{"supported":true,"subject_correct":true,"expected_fact_id":"fact-001","latency_ms":9000}],
  "recalls": [{"correct":true}],
  "named_switches": 0
}
```

Identity rows represent independent encounters; `expected: null` means unknown.
Fact rows represent persisted claims. `eligible_facts` includes supported facts
that were missed. `expected_fact_id` deduplicates coverage. Do not annotate based
on model outputs alone. Missing denominators remain insufficient evidence;
empty results and total abstention never establish accuracy. The evaluator
reports metrics and intentionally leaves overall acceptance incomplete until
scenario coverage and every gate in the protocol have been reviewed.

## Calibration and release decision

Use development recordings to tune similarity/margin, dwell/quality and speaker
thresholds. Freeze all settings before held-out evaluation. Compare normal,
dim, moving, occluded, noisy, overlapping and off-screen scenarios separately.
Include 500-person gallery load, 5-face stress, stop mid-sentence, provider
outage, process restart, correction and forgetting while jobs run. Collect
roughly 3,000 independent unknown trials before interpreting a zero-error run
as evidence near the 0.1% false-identity target. A small pilot is only a pilot.

No patient recordings or held-out accuracy dataset were available during the
implementation. The implementation report documents the measurements actually
performed, and does not claim the acceptance gates have passed.
