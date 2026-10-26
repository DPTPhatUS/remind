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
  Clear non-user speech is assumed to belong to the single visible visitor.
  Silence, overlapping speech, very short speech, and uncertain matches cannot
  establish personal facts. Anonymous transcription labels are local to each clip.
- Multiple faces or an uncertain face suspend profile learning. Changing visitors
  starts a separate encounter. Delayed clips retain their capture-time identity.
  Mouth analysis and Light-ASD are not used.
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

Temporary conversation clips default to a 1 GiB cap and 24-hour expiry. Failed
uploads pause capture and retain one clip in the current tab for retry or download.
Failed processing can be retried from Live. The existing bounded recording
transport is retained, including brief upload gaps; interrupted sentences may be
incomplete. Stop recording when an interaction should not be recorded.

This version assumes one visitor and a quiet conversation. A television or another
off-screen voice can be mistaken for the visitor. Voice and face operating points
are uncalibrated defaults, not probabilities. Automated fixtures and public-audio
model smokes do not establish real-world recognition or personal-fact accuracy.

The schema is rewritten in place, with no migration or older-version support.
Development data from the previous schema must be reset once before running this
rewrite. Normal restarts preserve all newly learned data. Startup never
intentionally wipes current memories.

Provider models remain configurable. The existing defaults require a separate
migration before the published GPT-4.1 mini (January 14, 2027) and
gpt-4o-transcribe-diarize (February 26, 2027) shutdowns. Changing transcription
models must preserve speaker labels and timestamps; it is not just a model-ID swap.

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

See [the API contract](backend/docs/API.md),
[the evaluation protocol](docs/testing/realtime-memory-evaluation.md), and
[browser/benchmark instructions](benchmarks/README.md).
