# Remind local API

Bind to `127.0.0.1`; all routes use `/api`. Only one camera session runs at a
time. Face templates and user voice representations are never returned publicly.

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/health` | Vision, cloud and user-voice readiness |
| GET | `/user/voice` | Reference status, model, version, sample count and errors |
| POST | `/user/voice` | `{samples:[base64,...]}`; three to five recordings, 3–20 seconds each |
| DELETE | `/user/voice` | Removes reference and increments its version |
| GET | `/people` | Identity, profile summary and current highlights |
| GET | `/people/{id}` | Profile, sourced facts and completed encounters |
| GET | `/people/{id}/thumbnail` | Local JPEG, no-store |
| PATCH | `/people/{id}` | `{version,fields:{name,relationship,age,notes}}` |
| PATCH | `/people/{id}/facts/{fact}` | `{version,value}`; correction preserves history |
| DELETE | `/people/{id}/facts/{fact}` | `{version}`; suppresses automatic recurrence |
| DELETE | `/people/{id}` | Stops active capture and forgets sources, memories and templates |
| GET | `/jobs` | Active/failed audio or learning jobs, plus attribution waits |
| POST | `/jobs/{id}/retry` | Retries retained failed work; invalid work returns 409 |
| POST | `/session` | `generation,memory_available,voice_ready,profile_learning_available` |
| POST | `/session/{generation}/stop` | Finalizes attribution and closes the encounter; jobs remain durable |
| POST | `/live/{generation}/clips?metadata=...` | Records a clip regardless of visitor identity |
| WS | `/live/{generation}/vision` | Timestamped JPEG packets and live candidate/encounter state |

Enrollment accepts raw base64 without a data-URL prefix, at most 4 MiB per sample
and 16 MiB per request. Recordings are decoded in memory and discarded. Silence,
insufficient speech, inconsistent samples, clipping and malformed media return
422. Unavailable local models return 503. Failed replacement preserves the saved
reference. Voice changes invalidate pending role-dependent writes.

## Clip processing

Metadata is URL-encoded JSON `{window_id,start_ms,end_ms}` using the same monotonic
clock as vision. A clip must last more than zero and at most ten seconds, contain
at most 16 MiB, and decode independently. Browser clips are synchronized WebM;
benchmarks send WAV. Media is decoded from its contents.

A successful upload returns:

```json
{
  "clip_id": "clip-uuid",
  "status": "transcribing",
  "jobs": [{"id":"job-uuid","kind":"audio","status":"pending","error":null}]
}
```

`(generation,window_id)` is idempotent. Receipts can report `transcribing`,
`waiting_for_attribution`, `learning`, `completed`,
`completed_without_attribution`, `failed`, or `cancelled`. An unrecognized
visitor is never an upload rejection. Ordinary HTTP validation, storage and
session-access errors still apply.

Audio jobs persist timestamped transcript turns and original voice roles before
learning. A clip may produce learning jobs for several encounters. Only complete
turns supported by one encounter are assigned; ambiguous transition turns remain
unattributed. Learning retries reuse saved transcripts.

Initial-candidate attribution can wait up to 30 seconds after receipt while audio
processing continues. Initial speech can be backfilled only from the same
continuously observed candidate. Finalized attribution never changes. Unattributed
transcripts and raw clips expire after 24 hours. Attributed textual evidence is
retained with memories. There is no public unattributed-history endpoint.

`GET /jobs` returns `id,clip_id,kind,status,attempts,error`. Job kinds are `audio`
and `learning`; a pending attribution item has kind `attribution` and status
`waiting_for_attribution`. Only failed processing jobs can be retried.

Each processing job has up to three automatic attempts, with a five-second retry
delay. A running job holds a three-minute lease, renewed every 30 seconds. A
manual retry resets a failed job's attempt count when its clip is still retained
and not cancelled. These are application retries; an external provider request
may be repeated after a crash. No exactly-once provider execution is promised.

Learning is serialized within an encounter and waits for earlier relevant work.
Restart recovers durable jobs and saved transcripts, and finalizes unresolved
live attribution without inventing continuity. Claim writes, summary updates,
job metrics and job completion commit together. Optional commit-duration timing
is updated afterward and cannot recreate a forgotten job.

The final clip may upload for two minutes after normal Stop until another
session replaces the capture capability. Forgetting cancels that capability.

Capture timestamps and absence deadlines share the session's source clock.
Receipt, expiration and lease times use epoch milliseconds internally; encounter
dates use UTC ISO strings. Processing durations use a performance clock.

## Vision and encounters

Packets contain a uint32 big-endian header length, UTF-8 JSON header, then JPEG.
The header contains `{version:1,generation,sequence,capture_ms}` (at most 8 KiB);
the JPEG is at most 2 MiB. The server processes the newest waiting frame.
Sequences and processed capture timestamps must increase.

A vision response contains:

```json
{
  "type":"vision", "generation":"session-uuid", "sequence":42, "capture_ms":10000,
  "detections":[{"box":[0.2,0.1,0.3,0.4],"quality":true}],
  "candidate":{"id":"candidate-uuid","person_id":"person-uuid",
               "box":[0.2,0.1,0.3,0.4],"confirmed":true,"quality":true},
  "encounter":{"id":"encounter-uuid","visitor_id":"person-uuid",
               "state":"confirmed","learning_available":true,
               "reason":"direct_confirmation","absence_deadline_ms":15000,
               "memory":{}},
  "processing_ms":15,"processed_fps":25,"dropped":0
}
```

Boxes are normalized `[x,y,width,height]`. All detections count, including poor
quality faces. There is at most one candidate; multiple detections reset it.
`candidate`, encounter IDs and `memory` can be null. `memory` has the same profile
contract as `/people/{id}`.

Encounter state is `confirmed`, `absent`, `paused`, or `identifying`. Learning may
continue for five seconds after the last confirmed presence when no competing
candidate exists. Healthy no-face observations support that allowance; camera
observations more than 500 ms apart do not. Another candidate, conflicting
identity or multiple faces pause learning immediately. A confirmed sole
replacement starts a new encounter immediately. Poor-quality observations cannot
extend the allowance indefinitely. A timeout ends the encounter.

The reminder stays visible during temporary absence. Boxes describe only current
detections. `learning_available` here describes visual attribution; personal writes
also require valid voice setup, a usable role, model verification and write guards.

## Facts

Facts expose `id,subject,category,predicate,value,temporal_status,valid_from,valid_to,
status,manual,evidence,created_at,updated_at`. Evidence contains `{segment_id,quote}`.
The subject is the visitor or a related subject scoped to that visitor. Mentioned
names never create face profiles. Current profile summaries exclude unresolved,
past, planned and related-person claims as established visitor identity.

Both evidence validation and final transactional writing require sources to be
associated with the target person and encounter. Voice role and association are
separate stored values. Models see association-ineligible turns as uncertain.
Person corrections and voice changes cannot be overwritten by delayed work.

The app assumes one conversation partner. An off-camera speaker during the
five-second allowance can be mistaken for that visitor. Visitor voice verification
is not implemented. Timing and recognition thresholds are uncalibrated.
