# Remind Backend

> **Note**: This release drops the caregiver / login flow and the review pipeline. The single Patient row is auto-created on startup. On an existing DB, **drop and recreate** the Postgres volume before `alembic upgrade head` — the migration is non-data-preserving (opted-out people are deleted; caregiver tables/columns are dropped).

Python/FastAPI backend for the desktop version of a real-time memory reminder assistant.

The backend runs locally for the desktop app, stores structured memory data in Postgres, uses
CompreFace for self-hosted enrolled-face recognition, and uses OpenAI for speech transcription,
structured memory extraction, and text embeddings.

## Product Rules

- One patient profile per desktop installation; single-patient, patient-owned.
- No caregiver / admin / login layer in this release — the running backend trusts the local caller. Do not expose this service beyond `localhost` without adding auth.
- Face recognition is limited to the patient's private memory history.
- Unknown and uncertain identities are shown with cautious wording.
- Raw video/audio is not stored continuously; only evidence snippets tied to interactions are saved.
- Captured facts are evidence until reviewed and confirmed (the model has a `confirmed` recognition status and a `MemoryClaim.confidence` field — there is no human-review endpoint in this release).
- The desktop frontend streams raw frames and PCM audio only; interaction detection runs in the backend.

## Setup

Database: this project uses the host's existing Postgres 17 with the `pgvector`
extension installed (no Postgres container in `docker-compose.yml`). Create the
DB and the extension once:

```bash
PGPASSWORD=postgres psql -h localhost -U postgres \
  -c "CREATE USER remind WITH PASSWORD 'remind' SUPERUSER;"
PGPASSWORD=postgres psql -h localhost -U postgres \
  -c "CREATE DATABASE remind OWNER remind;"
PGPASSWORD=remind psql -h localhost -U remind -d remind \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Then the usual flow:

```bash
cp .env.example .env       # fill in OPENAI_API_KEY + later COMPREFACE_API_KEY
uv sync
# docker compose is only used for the CompreFace stack — not the database.
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
```

API docs are available at:

```text
http://localhost:8000/docs
```

## CompreFace

The compose file includes a CompreFace stack on port `8000`, but CompreFace still requires initial
setup through its UI:

1. Start the stack:

   ```bash
   docker compose up -d compreface-postgres-db compreface-core compreface-api compreface-admin compreface-fe
   ```

2. Open `http://localhost:8000/login`.
3. Create a CompreFace account, application, and Face Recognition service.
4. Copy the service API key into `COMPREFACE_API_KEY` in `.env`.
5. Restart the backend.

The backend stores opaque CompreFace subject IDs. It does not use names as biometric identifiers.

## OpenAI

Set `OPENAI_API_KEY` in `.env`.

Default models:

- `OPENAI_TRANSCRIBE_MODEL=gpt-4o-transcribe`
- `OPENAI_TEXT_MODEL=gpt-5.5`
- `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`
- `OPENAI_EMBEDDING_DIMENSIONS=1536`

## Live Interaction Detection

The live WebSocket expects:

- `video.frame` messages with base64 JPEG or PNG frame bytes.
- `audio.chunk` messages with `audio/pcm`, 16 kHz, mono, signed 16-bit PCM.

The backend samples video frames, runs CompreFace recognition, runs local WebRTC VAD on audio,
buffers completed utterances, starts and closes interactions, transcribes completed speech
windows with OpenAI when configured, and stores transcripts/memory evidence for the patient.

Tunable defaults:

- `LIVE_FRAME_SAMPLE_INTERVAL_MS=500`
- `LIVE_INTERACTION_CANDIDATE_SCORE=0.45`
- `LIVE_INTERACTION_ACTIVE_SCORE=0.70`
- `LIVE_INTERACTION_MIN_CANDIDATE_MS=2000`
- `LIVE_INTERACTION_END_SILENCE_MS=8000`
- `LIVE_AUDIO_SAMPLE_RATE_HZ=16000`
- `LIVE_AUDIO_VAD_MODE=2`
- `LIVE_AUDIO_UTTERANCE_MAX_MS=12000`

## Main Endpoints

- `GET/PATCH /api/v1/patients/me` — single-patient profile (auto-created on startup).
- `GET/POST /api/v1/people` and `PATCH /api/v1/people/{person_id}` — managed people and their recognition status.
- `POST /api/v1/people/{person_id}/face-examples` — enroll a face example into CompreFace and link it to the person.
- `GET/POST /api/v1/interactions` and `POST /api/v1/interactions/{interaction_id}/transcripts` — interactions and transcript segments; the transcript POST runs OpenAI extraction + embedding when `OPENAI_API_KEY` is set.
- `POST /api/v1/memories/search` — vector search over the patient's `MemoryClaim` rows.
- `POST /api/v1/media/evidence` — store/retrieve evidence snippets tied to an interaction.
- `WS /api/v1/live/sessions/{session_id}` — raw `video.frame` / `audio.chunk` stream driving the orchestrator.

> Removed in this release (intentionally absent and asserted by `tests/integration/test_patient_owned_invariants.py`): any `/auth/*`, `/review-items/*`, or `/caregivers/*` route.

## Verification

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## Desktop Runtime Flow

1. Desktop UI opens a live WebSocket session.
2. UI streams raw `video.frame` and `audio.chunk` messages.
3. Backend samples frames, runs CompreFace, runs VAD, and detects interaction start/end.
4. Backend stores interactions, participants, transcripts, memory claims, events, and selected evidence snippets — all keyed to the single patient row.
5. OpenAI adapters transcribe utterances, extract structured memory evidence from transcript text, and embed memory search queries when configured.
6. Caller promotes evidence into confirmed memory by PATCHing the relevant `people` / `memory_claims` rows directly (no review endpoint in this release).
7. Reminder policy returns patient-safe text:
   - high-confidence confirmed/trusted: direct name.
   - medium confidence: `This may be ...`
   - introduced only: `They introduced themselves as ...`
   - opted-out/sensitive: hidden from patient display.
