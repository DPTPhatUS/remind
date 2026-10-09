# Remind local API

Base: `/api`. Bind the backend to `127.0.0.1`. Allowed origins are localhost
ports 5173 and 8000 by default. A random session generation is the live capture
capability. Only one active capture session is allowed; other tabs receive 409.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Vision readiness, memory/speaker status, calibration status |
| GET | `/people` | Person records, no template vectors |
| GET | `/people/{id}` | Fields, sourced facts, completed encounters |
| GET | `/people/{id}/thumbnail` | Local JPEG thumbnail, no-cache |
| PATCH | `/people/{id}` | `{version, fields: {name, relationship, age, notes}}`; stale version returns 409 |
| DELETE | `/people/{id}` | Forget templates, facts and related shared text; cancel stale jobs |
| GET | `/jobs` | Pending/running/failed job status and attempts |
| POST | `/session` | Create owner; returns `{generation, memory_available}` |
| POST | `/session/{generation}/stop` | Close encounter; jobs remain durable |
| POST | `/live/{generation}/clips?metadata=...` | Binary independently decodable WebM, ≤16 MiB |
| WS | `/live/{generation}/vision` | Binary camera packets, JSON face results |

Clip query metadata is URL-encoded JSON: `window_id`, `start_ms`, `end_ms`.
Times use the browser's monotonic performance timeline, identical to vision.
Clips carry audio/video in the same container. Jobs snapshot participant IDs and
versions before the upload is acknowledged. A clip with no established
participants is ignored explicitly. Memory queue capacity errors are visible.

Vision packet: uint32 big-endian header length, UTF-8 JSON header, JPEG bytes.
Header: `{version: 1, generation, sequence, capture_ms, width, height}`.
Header limit 8 KiB, JPEG limit 2 MiB. Out-of-order and old-generation packets
are discarded. The server keeps one running and one newest waiting frame.

Result: `{type: 'vision', generation, sequence, capture_ms, tracks,
processing_ms, processed_fps, dropped}`. Each track contains `track_id`,
`person_id` (nullable), `state`, normalized `[x,y,width,height]`, and a memory
card. State is observing/unknown/ambiguous/remembered. No raw face embeddings
are sent to the browser. Result timestamps allow same-clock capture-to-display
age measurement. The browser rejects results older than 500 ms and expires
missing boxes. `processed_fps` is a session-average fresh completion count,
not a 30-minute acceptance result.

No standalone patient, relationship graph, semantic-search, media CRUD or
caregiver APIs remain.

`POST /api/jobs/{id}/retry` retries a terminal failed job whose encounter has not been forgotten. Cancelled jobs cannot be retried.

Final-clip upload retries remain valid for two minutes after Stop, provided no new session has replaced that generation. Forget invalidates the saved timeline and affected encounters.
