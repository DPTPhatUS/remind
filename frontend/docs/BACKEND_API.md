# Remind Backend API

This document describes the implemented desktop backend API.

Base URL:

```text
http://localhost:8000/api/v1
```

Interactive OpenAPI docs:

```text
http://localhost:8000/docs
```

## Authentication

Most endpoints require a bearer token:

```http
Authorization: Bearer <access_token>
```

The first admin caregiver account is created through `POST /auth/bootstrap-admin`.
After at least one admin exists, bootstrap returns `409 Conflict`.

### Common Errors

```json
{
  "detail": "Error message"
}
```

Common status codes:

- `401 Unauthorized`: missing, invalid, or expired bearer token.
- `403 Forbidden`: valid user without required permission.
- `404 Not Found`: requested entity was not found.
- `409 Conflict`: resource already exists or bootstrap is no longer allowed.
- `422 Unprocessable Entity`: request validation failed.

## Health

### `GET /health`

Returns runtime status.

Response:

```json
{
  "status": "ok",
  "app": "Remind Backend",
  "environment": "development"
}
```

## Auth

### `POST /auth/bootstrap-admin`

Creates the first caregiver admin account and the local patient profile.

Request:

```json
{
  "email": "caregiver@example.com",
  "display_name": "Primary Caregiver",
  "password": "strong-password",
  "patient_display_name": "Patient Name"
}
```

Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_at": "2026-06-16T20:00:00+00:00"
}
```

### `POST /auth/login`

Authenticates a caregiver/admin account.

Request:

```json
{
  "email": "caregiver@example.com",
  "password": "strong-password"
}
```

Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_at": "2026-06-16T20:00:00+00:00"
}
```

### `GET /auth/me`

Returns the current authenticated user.

Response:

```json
{
  "id": "user-id",
  "email": "caregiver@example.com",
  "display_name": "Primary Caregiver",
  "role": "admin"
}
```

## Patient

### `GET /patients/me`

Returns the patient profile for the current desktop installation.

Response:

```json
{
  "id": "patient-id",
  "display_name": "Patient Name",
  "date_of_birth": null,
  "preferences": {},
  "accessibility_settings": {},
  "created_at": "2026-06-16T20:00:00Z",
  "updated_at": "2026-06-16T20:00:00Z"
}
```

### `PATCH /patients/me`

Updates patient profile fields.

Request:

```json
{
  "display_name": "Patient Name",
  "date_of_birth": "1945-05-01",
  "preferences": {
    "audio_prompts": true
  },
  "accessibility_settings": {
    "large_text": true
  }
}
```

Response: `PatientResponse`

## People

Recognition statuses used by the backend:

- `unknown`
- `seen_before`
- `introduced`
- `confirmed`
- `trusted`
- `opted_out`

### `GET /people`

Lists people for the current patient.

Response:

```json
[
  {
    "id": "person-id",
    "patient_id": "patient-id",
    "display_name": "David",
    "relationship_to_patient": "neighbor",
    "notes": "Lives next door.",
    "recognition_status": "introduced",
    "consent_status": "unknown",
    "sensitive": false,
    "created_at": "2026-06-16T20:00:00Z",
    "updated_at": "2026-06-16T20:00:00Z"
  }
]
```

### `POST /people`

Creates a person profile.

Request:

```json
{
  "display_name": "David",
  "relationship_to_patient": "neighbor",
  "notes": "Lives next door.",
  "recognition_status": "introduced",
  "consent_status": "unknown",
  "sensitive": false
}
```

Response: `PersonResponse`

### `PATCH /people/{person_id}`

Updates a person profile.

Request:

```json
{
  "display_name": "David Tran",
  "relationship_to_patient": "neighbor",
  "recognition_status": "confirmed",
  "consent_status": "granted"
}
```

Response: `PersonResponse`

### `POST /people/{person_id}/face-examples`

Uploads a reference face image to CompreFace and links the opaque CompreFace
subject ID to the person.

Content type: `multipart/form-data`

Fields:

- `file`: image file.

Response:

```json
{
  "person_id": "person-id",
  "subject": "person-person-id-generated-uuid",
  "provider_image_id": "compreface-image-id"
}
```

## Relationships

### `GET /relationships`

Lists relationships for the current patient.

Response:

```json
[
  {
    "id": "relationship-id",
    "patient_id": "patient-id",
    "from_person_id": "person-id",
    "to_person_id": null,
    "relationship_type": "neighbor",
    "confidence": 1.0,
    "confirmed_by_user_id": "user-id",
    "source_claim_id": null,
    "created_at": "2026-06-16T20:00:00Z",
    "updated_at": "2026-06-16T20:00:00Z"
  }
]
```

### `POST /relationships`

Creates a caregiver-confirmed relationship.

Request:

```json
{
  "from_person_id": "person-id",
  "to_person_id": null,
  "relationship_type": "neighbor",
  "confidence": 1.0
}
```

Response: `RelationshipResponse`

## Events

### `GET /events`

Lists memory events.

Response:

```json
[
  {
    "id": "event-id",
    "patient_id": "patient-id",
    "title": "Helped with groceries",
    "description": "David helped bring groceries upstairs.",
    "event_date": "2026-06-15",
    "confidence": 1.0,
    "emotional_importance": "normal",
    "patient_visible": true,
    "created_at": "2026-06-16T20:00:00Z",
    "updated_at": "2026-06-16T20:00:00Z"
  }
]
```

### `POST /events`

Creates an event.

Request:

```json
{
  "title": "Helped with groceries",
  "description": "David helped bring groceries upstairs.",
  "event_date": "2026-06-15",
  "confidence": 1.0,
  "emotional_importance": "normal",
  "patient_visible": true
}
```

Response: `EventResponse`

## Interactions

### `GET /interactions`

Lists captured interactions.

Response:

```json
[
  {
    "id": "interaction-id",
    "patient_id": "patient-id",
    "started_at": "2026-06-16T10:42:00Z",
    "ended_at": null,
    "summary": "David introduced himself as a neighbor.",
    "confidence": 0.86,
    "status": "open",
    "created_at": "2026-06-16T20:00:00Z",
    "updated_at": "2026-06-16T20:00:00Z"
  }
]
```

### `POST /interactions`

Creates an interaction record.

Request:

```json
{
  "started_at": "2026-06-16T10:42:00Z",
  "confidence": 0.86,
  "summary": "Likely direct conversation."
}
```

Response: `InteractionResponse`

### `POST /interactions/{interaction_id}/transcripts`

Adds a transcript segment to an interaction.

Request:

```json
{
  "text": "Hi, I'm David. I live next door.",
  "speaker_label": "speaker_1",
  "confidence": 0.91,
  "started_at_ms": 1200,
  "ended_at_ms": 5200
}
```

Response:

```json
{
  "id": "transcript-id",
  "interaction_id": "interaction-id",
  "speaker_label": "speaker_1",
  "text": "Hi, I'm David. I live next door.",
  "confidence": 0.91,
  "started_at_ms": 1200,
  "ended_at_ms": 5200,
  "created_at": "2026-06-16T20:00:00Z",
  "updated_at": "2026-06-16T20:00:00Z"
}
```

## Review Queue

### `GET /review-items`

Lists pending caregiver review items.

Response:

```json
[
  {
    "id": "review-id",
    "patient_id": "patient-id",
    "item_type": "new_person_candidate",
    "target_type": "person",
    "target_id": "person-id",
    "title": "Review new person: David",
    "summary": null,
    "payload": {},
    "status": "pending",
    "created_at": "2026-06-16T20:00:00Z",
    "updated_at": "2026-06-16T20:00:00Z"
  }
]
```

### `PATCH /review-items/{item_id}`

Records a caregiver decision.

Request:

```json
{
  "status": "approved",
  "payload": {
    "confirmed_display_name": "David",
    "notes": "Confirmed by caregiver."
  }
}
```

Response: `ReviewItemResponse`

## Memories

### `POST /memories/search`

Searches visible memory claims with a text query.

Request:

```json
{
  "query": "groceries",
  "limit": 10
}
```

Response:

```json
[
  {
    "id": "claim-id",
    "patient_id": "patient-id",
    "subject_type": "interaction",
    "subject_id": "interaction-id",
    "claim_text": "David said he lives next door.",
    "structured_value": {},
    "source_type": "interaction",
    "source_id": "interaction-id",
    "confidence": 0.5,
    "confirmed_by_user_id": null,
    "patient_visible": true,
    "created_at": "2026-06-16T20:00:00Z",
    "updated_at": "2026-06-16T20:00:00Z"
  }
]
```

Current implementation note: memory search uses database text matching. The schema and
database include pgvector support for future embedding search.

## Media

### `POST /media/evidence`

Uploads an evidence snippet tied to an interaction.

Content type: `multipart/form-data`

Fields:

- `file`: evidence file.
- `asset_type`: expected values are application-level strings such as `frame`,
  `audio`, or `clip`.
- `interaction_id`: optional interaction ID.

Response:

```json
{
  "id": "media-id",
  "patient_id": "patient-id",
  "interaction_id": "interaction-id",
  "asset_type": "frame",
  "storage_path": ".local/evidence/patient-id/file.jpg",
  "content_type": "image/jpeg",
  "sha256": "hex-digest",
  "size_bytes": 12345,
  "retention_expires_at": "2026-07-16T20:00:00+00:00",
  "status": "active",
  "created_at": "2026-06-16T20:00:00Z",
  "updated_at": "2026-06-16T20:00:00Z"
}
```

## Live WebSocket

### `WS /live/sessions/{session_id}`

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

#### `frame.observed`

Sends observed recognition context from the desktop client. The current
implementation composes a reminder from the supplied fields.

```json
{
  "type": "frame.observed",
  "payload": {
    "display_name": "David",
    "recognition_status": "introduced",
    "similarity": 0.88,
    "relationship_to_patient": "neighbor",
    "recent_event": "said he helped with groceries yesterday",
    "sensitive": false
  }
}
```

Response:

```json
{
  "type": "reminder.update",
  "payload": {
    "title": "They introduced themselves as David.",
    "lines": [
      "They said they are your neighbor.",
      "They said he helped with groceries yesterday."
    ],
    "patient_visible": true,
    "requires_review": true
  }
}
```

#### `audio.chunk`

Accepted by the session orchestrator. Current implementation does not yet
return a response.

```json
{
  "type": "audio.chunk",
  "payload": {
    "content_type": "audio/webm",
    "data": "<base64-audio>"
  }
}
```

#### `interaction.marker`

Accepted by the session orchestrator. Current implementation does not yet
return a response.

```json
{
  "type": "interaction.marker",
  "payload": {
    "marker": "conversation_started"
  }
}
```

#### `correction.submitted`

Reports a patient/caregiver correction from the live UI.

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
    "title": "Correction saved for caregiver review.",
    "lines": [],
    "requires_review": true
  }
}
```

#### `session.stop`

Ends the websocket loop.

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
- OpenAI provider adapters exist for transcription, memory extraction, and embeddings,
  but endpoint-level orchestration for those providers is still minimal.
- Date/time fields are currently represented as strings in several API models.
