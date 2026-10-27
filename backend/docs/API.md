# Remind local API

Bind to `127.0.0.1`; all routes use `/api`. Only one capture session runs at a
time. Face templates and user voice representations are never returned publicly.

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/health` | Vision, cloud, voice-model/reference readiness and profile-learning availability |
| GET | `/user/voice` | `ready,reference_saved,model_available,error,version,model,sample_count,updated_at` |
| POST | `/user/voice` | JSON `{samples:[base64,...]}`, three to five recordings, 3–20 seconds each; returns status |
| DELETE | `/user/voice` | Removes voice reference, increments version, invalidates pending role-dependent work |
| GET | `/people` | Person identity fields, profile summary, up to three current highlights |
| GET | `/people/{id}` | Person plus structured sourced facts and completed encounters |
| GET | `/people/{id}/thumbnail` | Local JPEG, no-store |
| PATCH | `/people/{id}` | `{version,fields:{name,relationship,age,notes}}`; manual authority, stale version409 |
| PATCH | `/people/{id}/facts/{fact}` | `{version,value}`; manual accepted correction, retains history |
| DELETE | `/people/{id}/facts/{fact}` | JSON `{version}`; dismisses fact and suppresses automatic recurrence |
| DELETE | `/people/{id}` | Forgets sources, derived memories, templates; invalidates jobs and active timeline |
| GET | `/jobs` | Pending/running/failed status, attempts, error |
| POST | `/jobs/{id}/retry` | Retries retained failed work; cancelled/forgotten work409 |
| POST | `/session` | `generation,memory_available,voice_ready,profile_learning_available` |
| POST | `/session/{generation}/stop` | Closes encounter; background processing remains durable |
| POST | `/live/{generation}/clips?metadata=...` | Independently decodable audio: browser WebM or benchmark WAV, at most16MiB |
| WS | `/live/{generation}/vision` | Camera packets and normalized face results |

Enrollment accepts raw base64 (no data-URL prefix), max4MiB per sample and16MiB
request. Media is decoded in memory and discarded after enrollment. Silence,
insufficient speech, inconsistent samples, clipping or malformed media returns422.
Unavailable local models/dependencies returns503. Failed replacement preserves the
previous reference. Version increments prevent delayed writes using an old reference.

Facts expose `id,subject,category,predicate,value,temporal_status,valid_from,valid_to,
status,manual,evidence,created_at,updated_at`. Evidence is a structured array of
`{segment_id,quote}`; IDs are globally scoped within persisted dialogue.
The subject is `visitor` or a related subject scoped to that visitor. Categories
cover identity, relationship, age, work, education, residence, interests,
preferences, routines, family, experiences, plans and other background.
Temporal states are current/past/planned; lifecycle states are
accepted/conflict/superseded/dismissed. Profile summaries/highlights exclude
unresolved, past, planned, and related-person facts as established current identity.

Clip query metadata is URL-encoded JSON `{window_id,start_ms,end_ms}` on the
browser's monotonic clock, shared with vision. Upload snapshots the original
visitor/encounter, participant versions, voice-reference version and face timeline.
Clips spanning different encounters are not assigned to the current visitor.
Multiple/unknown faces make overlapping speech ineligible for personal learning.
Voice roles user/visitor/uncertain are computed within each clip, never inferred
from reused anonymous speaker labels across clips.

The face/video benchmarks use a source-relative clock for vision and, in video mode,
clip metadata. It sends clean WAV bodies through the same clip endpoint; media
is decoded from its contents. Browser capture continues to send synchronized WebM.

Vision packet: uint32 big-endian header length, UTF-8 JSON header, JPEG bytes.
Header `{version:1,generation,sequence,capture_ms,width,height}`, max8KiB;
JPEG max2MiB. Server queue keeps one running and one newest waiting frame.
Results include normalized boxes, identities and memory cards. The browser rejects
results older than500ms and expires missing boxes. Cards refresh after memory commits.

The final clip can retry for two minutes after Stop until a new generation
replaces the capture capability. There are no legacy API/schema compatibility
contracts. No patient selector, relationship graph service, or approval queue.
