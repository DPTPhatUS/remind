# Remind

A local memory assistant for English one-on-one conversations. Remind recognizes
the visitor automatically, remembers supported information from the conversation,
and shows a short reminder when that person returns. No person selection or fact
approval is required during normal encounters.

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

Open <http://127.0.0.1:5173>. A helper first opens **Voice setup**, records three
short samples containing only the user's voice, and saves the reference. Samples
must contain clear speech from the same person. The reference can be replaced or
removed later. Raw setup recordings are decoded in memory and are not saved.

Then choose **Start camera** and allow camera and microphone access. Face
recognition and enrollment are automatic. **Stop camera** releases both devices
and flushes the final clip. Keep the backend on localhost.

## How learning works

- Clear unfamiliar faces are enrolled after sustained observation. Returning
  faces require repeated matching agreement. Names are learned from conversation
  or can be corrected in People; there is no name-selection step.
- Local CPU SpeechBrain ECAPA-TDNN compares speech with the saved user reference.
  Clear non-user speech is assumed to belong to the selected encounter visitor.
  Silence, detected overlapping turns, insufficient usable speech, and uncertain
  matches cannot establish personal facts. Anonymous transcription labels are
  local to each clip. Overlap missed by transcription can still be misclassified.
- Audio is transcribed even before a visitor is identified. One temporary face
  candidate groups observations for recognition or enrollment. Initial speech can
  be associated later only when that same candidate supports continuity.
- The selected visitor remains eligible for up to five seconds without confirmed
  visual presence. Another candidate, conflicting identity, multiple faces or stale
  camera data pause learning. A confirmed replacement starts a separate encounter.
  Whole speech turns are associated at capture time; one clip can contain several
  encounters. Ambiguous transition speech remains unattributed.
- OpenAI provides English speaker-labelled transcription, contextual fact
  extraction, and a separate evidence-verification pass. Recent dialogue spans
  clip boundaries. Questions alone do not establish their premises: facts require
  the visitor's own statement or clear confirmation.
- The speaker and the subject are distinct. "My brother teaches" describes the
  visitor's brother, not the visitor's job. Mentioned people stay associated with
  that visitor; names in a transcript do not create or merge face profiles.
- Individual sourced facts cover background, work, education, residence,
  interests, preferences, routines, relatives, experiences, and plans. Compatible
  facts accumulate; repeats add evidence. Explicit corrections and changes
  preserve history. Unexplained contradictions remain unresolved. Plans never
  become completed events merely because their date passes.
- The live reminder contains identity, up to three established current highlights,
  and the previous completed encounter. People contains the fuller profile,
  temporal details, source quotes, and optional correction/removal controls.
- Without an API key, face recognition still works. Without a usable user voice
  reference, conversation summaries can be saved but profiles are not updated.

Manual corrections take precedence. Forgetting a person removes associated
source material and derived memories and invalidates pending work. Replacing or
removing the voice reference invalidates pending role-dependent processing.

## Data and operating assumptions

SQLite, face templates, and user voice representations remain local at
`backend/.local/`. The installer downloads pinned, checksum-verified YuNet,
SFace, and ECAPA model assets. Audio is sent to OpenAI for transcription;
transcript context and candidate facts are sent for extraction and verification.

Temporary conversation clips have a 1 GiB cap and 24-hour expiry. Unattributed
transcripts also expire after 24 hours; attributed textual evidence stays with
memories. Initial identity attribution can wait 30 seconds without blocking
transcription. Learning retries reuse saved audio-stage results. Failed
uploads pause capture and retain one clip in the current tab for retry or download.
Failed processing can be retried from Live. The existing bounded recording
transport is retained, including brief upload gaps; interrupted sentences may be
incomplete. Stop recording when an interaction should not be recorded.

This version assumes one visitor and a quiet conversation. A television or another
off-screen voice can be mistaken for the visitor, including during the five-second
absence allowance. Voice and face operating points
are uncalibrated defaults, not probabilities. Automated fixtures and public-audio
model smokes do not establish real-world recognition or personal-fact accuracy.

Normal restarts preserve learned memories. The current SQLite schema is created
on first startup; there is no migration or older-version support.

Extraction and verification default to `gpt-6-luna`; transcription defaults to
`gpt-4o-transcribe-diarize`. Model IDs are configurable in `backend/.env`.
A transcription provider must return speaker labels and timestamps; changing
providers may require an adapter rather than only changing the model ID.

## Code layout

| Location | Responsibility |
| --- | --- |
| `backend/src/remind/app.py` | HTTP routes, request validation, and local access guards |
| `backend/src/remind/runtime.py` | Startup, shutdown, models, and background tasks |
| `backend/src/remind/live/` | Camera transport, one face candidate, and encounter association |
| `backend/src/remind/vision/` | Face detection, recognition, and model installation |
| `backend/src/remind/audio/` | Audio decoding, user-voice verification, and cloud providers |
| `backend/src/remind/memory/` | Evidence validation, consolidation, and durable jobs |
| `backend/src/remind/benchmark/` | Four benchmark paths: audio, conversation, face, and video |
| `backend/src/remind/database.py` | Current SQLite schema and transactions |
| `frontend/src/features/` | Browser capture, setup, and profile interaction logic |
| `frontend/src/pages/` | Live view, voice setup, and People screens |
| `frontend/e2e/` | Application UI integration tests |
| `benchmarks/` | Evaluation instructions, manifest examples, and public-footage audit |

Development checks are installed by default by `uv sync`.
Use `uv sync --no-dev --extra speaker` when only runtime dependencies are needed.

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
# Browser fixture setup is described in benchmarks/README.md.
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

See [the API contract](backend/docs/API.md),
[attribution implementation and cleanup](backend/docs/ATTRIBUTION.md),
[the evaluation protocol](docs/testing/realtime-memory-evaluation.md), and
[benchmark and browser test instructions](benchmarks/README.md).
