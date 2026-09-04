# Remind Backend API

This document describes the implemented desktop backend API for the patient-owned
release. The caregiver / login flow and the review pipeline have been removed; the
single Patient row is auto-created on startup.

Base URL:

```text
http://localhost:8000/api/v1
```

Interactive OpenAPI docs:

```text
http://localhost:8000/docs
```

## Common Errors

```json
{
  "detail": "Error message"
}
```

Common status codes:

- `404 Not Found`: requested entity was not found.
- `409 Conflict`: resource already exists.
- `422 Unprocessable Entity`: request validation failed.

## Health

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/v1/health` | Returns runtime status. |

## Patient

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/v1/patients/me` | Returns the patient profile for the current desktop installation. |
| PATCH | `/api/v1/patients/me` | Updates patient profile fields. |

## People

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/v1/people` | Lists people for the current patient. |
| POST | `/api/v1/people` | Creates a person profile. |
| PATCH | `/api/v1/people/{person_id}` | Updates a person profile. |
| POST | `/api/v1/people/{person_id}/face-examples` | Uploads a reference face image to CompreFace and links the subject ID to the person. |

Recognition statuses used by the backend:

- `unknown`
- `seen_before`
- `introduced`
- `confirmed`
- `trusted`
- `opted_out`

## Relationships

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/v1/relationships` | Lists relationships for the current patient. |
| POST | `/api/v1/relationships` | Creates a relationship. |

## Events

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/v1/events` | Lists memory events. |
| POST | `/api/v1/events` | Creates an event. |

## Interactions

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/v1/interactions` | Lists captured interactions. |
| POST | `/api/v1/interactions` | Creates an interaction record. |
| POST | `/api/v1/interactions/{interaction_id}/transcripts` | Adds a transcript segment to an interaction. |

## Memories

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `/api/v1/memories/search` | Searches visible memory claims with a text query. |

When `OPENAI_API_KEY` is configured, the backend embeds the query and searches
stored `memory_claims.embedding` values with pgvector cosine distance. Without
OpenAI configuration, it falls back to database text matching.

## Media

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `/api/v1/media/evidence` | Uploads an evidence snippet tied to an interaction. |
| POST | `/api/v1/media/cleanup-expired` | Deletes expired active evidence files from local storage and marks their media rows as `deleted`. |

## Live WebSocket

| Method | Path | Description |
| ------ | ---- | ----------- |
| WS | `/api/v1/live/sessions/{session_id}` | Live session socket for streaming frames and audio. |

WebSocket URL:

```text
ws://localhost:8000/api/v1/live/sessions/{session_id}
```

On connection, the server sends:

```json
{
  "type": "session.ready",
  "payload": {
    "session_id": "session-id"
  }
}
```

### Inbound Messages

#### `session.start`

Starts or re-announces a live session.

```json
{
  "type": "session.start",
  "payload": {}
}
```

Response:

```json
{
  "type": "session.ready",
  "payload": {
    "session_id": "session-id"
  }
}
```

#### `video.frame`

Sends a raw image frame. The desktop frontend must not send identity,
relationship, confidence, or reminder fields. The backend samples frames,
calls CompreFace, resolves the subject, updates interaction detection, and
returns one or more events.

```json
{
  "type": "video.frame",
  "payload": {
    "image_base64": "<base64-jpeg>",
    "content_type": "image/jpeg",
    "filename": "frame.jpg",
    "sequence": 42,
    "captured_at_ms": 12000
  }
}
```

Typical response events:

```json
[
  {
    "type": "media.accepted",
    "payload": {
      "media_type": "frame",
      "content_type": "image/jpeg",
      "size_bytes": 48122
    }
  },
  {
    "type": "recognition.update",
    "payload": {
      "subject": "compreface-subject-id",
      "similarity": 0.97,
      "face_probability": 0.99,
      "box": {
        "probability": 0.99,
        "x_min": 1,
        "y_min": 2,
        "x_max": 3,
        "y_max": 4
      },
      "reminder": {
        "title": "Anna",
        "lines": [
          "Your daughter"
        ],
        "patient_visible": true,
        "requires_review": false
      }
    }
  },
  {
    "type": "reminder.update",
    "payload": {
      "title": "Anna",
      "lines": [
        "Your daughter"
      ],
      "patient_visible": true,
      "requires_review": false
    }
  }
]
```

`frame.observed` is temporarily accepted only when it contains `image_base64`.
Payloads that include client-supplied identity or reminder context are rejected:

```json
{
  "type": "session.error",
  "payload": {
    "message": "frame.observed only accepts image_base64 during migration."
  }
}
```

#### `audio.chunk`

Sends raw PCM audio. The frontend does not run speech detection; it only streams
chunks. The backend validates the format, runs local VAD, buffers utterances,
starts/ends interactions, and sends completed utterances to OpenAI transcription
when configured.

```json
{
  "type": "audio.chunk",
  "payload": {
    "content_type": "audio/pcm",
    "sample_rate_hz": 16000,
    "channels": 1,
    "sample_width_bits": 16,
    "sequence": 88,
    "captured_at_ms": 12500,
    "data": "<base64-signed-16-bit-mono-pcm>"
  }
}
```

Accepted response:

```json
{
  "type": "media.accepted",
  "payload": {
    "media_type": "audio",
    "content_type": "audio/pcm",
    "size_bytes": 640
  }
}
```

Interaction detection events may be sent after media acceptance:

```json
{
  "type": "interaction.candidate",
  "payload": {
    "confidence": 0.7,
    "reason": "face_and_speech_detected"
  }
}
```

```json
{
  "type": "interaction.started",
  "payload": {
    "interaction_id": "interaction-id",
    "confidence": 0.8,
    "reason": "stable_face_and_speech",
    "candidate_ms": 2100
  }
}
```

Completed utterance response:

```json
{
  "type": "transcript.received",
  "payload": {
    "interaction_id": "interaction-id",
    "content_type": "audio/pcm",
    "size_bytes": 12345,
    "text": "Hi, I am David.",
    "started_at_ms": 12500,
    "ended_at_ms": 14120
  }
}
```

Ended interaction response:

```json
{
  "type": "interaction.ended",
  "payload": {
    "interaction_id": "interaction-id",
    "confidence": 0.0,
    "duration_ms": 8200,
    "reason": "no_recent_face_or_speech"
  }
}
```

#### `interaction.marker`

Acknowledges an interaction marker.

```json
{
  "type": "interaction.marker",
  "payload": {
    "marker": "conversation_started"
  }
}
```

Response:

```json
{
  "type": "interaction.marked",
  "payload": {
    "marker": "conversation_started"
  }
}
```

#### `correction.submitted`

Reports a patient correction from the live UI.

```json
{
  "type": "correction.submitted",
  "payload": {
    "target_type": "recognition",
    "target_id": "person-id",
    "correction": "wrong_person"
  }
}
```

Response:

```json
{
  "type": "reminder.update",
  "payload": {
    "title": "Correction saved.",
    "lines": [],
    "requires_review": false
  }
}
```

#### `session.stop`

Ends the websocket loop. If an interaction is active, the backend closes it and
returns `interaction.ended`.

```json
{
  "type": "session.stop",
  "payload": {}
}
```

### Unsupported WebSocket Message

Response:

```json
{
  "type": "session.error",
  "payload": {
    "message": "Unsupported message type: unknown.type"
  }
}
```

## Patient-Safe Reminder Policy

The live reminder policy avoids presenting uncertain information as confirmed fact.

- `trusted` or `confirmed` with high similarity returns the direct display name.
- `confirmed` with medium similarity returns `This may be <name>.`
- `introduced` returns `They introduced themselves as <name>.`
- `seen_before` says the patient has seen the person before but the name is not confirmed.
- `opted_out` or sensitive profiles are hidden from patient display.

## Implementation Notes

- The backend package is intentionally flat under `src/`.
- The CompreFace integration stores opaque subject IDs instead of names.
- Uploaded media is stored under `.local/evidence/`, which is ignored by git.
- OpenAI extraction and embedding providers are wired into transcript ingestion
  and memory search when `OPENAI_API_KEY` is configured.
- Date/time fields are currently represented as strings in several API models.
