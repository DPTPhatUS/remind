# Remind Real-Time Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Execution status:** User approved and authorized implementation in this checkout.
The task-level outcomes, implementation adjustments and outstanding empirical
acceptance work are recorded in [the execution ledger](../execution/progress.md).
The original checklist below is retained as the approved target, not as a claim
that every empirical acceptance gate has been met.

**Goal:** Complete the single-patient encounter-to-memory-to-recognition flow, with measured fresh vision throughput of at least 10 fps on the user's laptop.

**Architecture:** A local FastAPI process owns SQLite, a warm CPU vision worker, and a separate durable memory worker. The browser displays camera video and identity overlays; audio and synchronized clips feed cloud transcription and local speaker attribution independently of vision. Accepted facts carry source evidence, and returning faces retrieve a completed previous encounter.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy/aiosqlite, NumPy, OpenCV YuNet/SFace, PyTorch Light-ASD adapter, PyAV, WebRTC VAD, OpenAI SDK; existing React/Vite/TypeScript and Vitest, browser testing with Playwright if no Browser plugin is available.

**Spec:** [Approved design](../specs/2026-10-08-realtime-memory-design.md) and [evaluation protocol](../../testing/realtime-memory-evaluation.md).

## Global Constraints

- Single patient, patient-owned; no backward compatibility or legacy API shims.
- English-only conversation support; cloud audio processing approved.
- The baseline workload is 1–3 visible faces and up to 500 stored people.
- At least 10 freshly processed video frames per second; no counting preview or interpolation as inference.
- Capture 1280×720 around 30 fps; initial inference width 640 pixels, original aspect ratio.
- At most one frame in inference and one newest pending frame.
- Initial enrollment: 2-second dwell and at least 5 usable observations; all thresholds configurable and calibrated.
- Initial maximum speech window 8 seconds; final partial window flushed on Stop.
- Audio-visual reference inputs: 25 fps video and 16 kHz audio; gaps cannot become invented evidence.
- Manual corrections override automatic extraction. Similarity is not a calibrated probability.
- Automatic speaker attribution and measured performance are release gates.
- All provider keys, patient data, model binaries, recordings, and benchmark media stay out of source control.
- Preserve the dirty checkout; no reset, blanket staging, or disposal of unrelated work.

## Review Focus

1. A visitor changes while old transcription is pending: facts stay attached to the original immutable encounter, never the new visitor (Tasks 4/6).
2. Two visually similar people cross or one is replaced during occlusion: clear uncertain names instead of inheriting identity from position (Task 3).
3. Browser suspension or a camera/audio format change breaks synchronization: invalidate affected attribution and restart timing explicitly (Tasks 5/7).
4. Forgetting one member of a shared encounter while a worker is running: no residual or recreated personal facts/media (Tasks 1/6/8).
5. A second tab starts capture while the first still owns the live session: enforce one capture owner and keep both data and device cleanup deterministic (Tasks 4/7).

## Hardware and runtime decisions

Verified on 2026-10-08: i7-1360P, 16 logical CPUs, approximately 16 GB RAM,
RTX 2050 with 4096 MiB VRAM, working NVIDIA driver 615.71.09. FFmpeg exists.
The existing backend environment has NumPy but lacks OpenCV, aiosqlite, PyTorch,
ONNX Runtime, and PyAV. These are observations, not a performance benchmark.

Use `opencv-python-headless` on CPU first: official prebuilt OpenCV Python
wheels are CPU-only. Do not silently select a CUDA backend that is unavailable.
Use a separate optional `speaker` dependency group for PyTorch/PyAV and a
runtime capability check for CPU/CUDA speaker inference. Pin a supported
PyTorch wheel after checking installation compatibility; `nvidia-smi`'s CUDA
version is driver capability, not proof that a toolkit or PyTorch is installed.
Keep only one speaker model resident and bound its batches to fit 4 GB VRAM.
[OpenCV packaging](https://github.com/opencv/opencv-python),
[PyTorch installation](https://pytorch.org/get-started/locally/).

Recommend native execution in this session because storage, tracking, transport,
and attribution share several interfaces. Follow the selected execution skill's
review workflow once the user reviews this plan and chooses execution mode.
The tasks form one integration sequence; intermediate milestones are testable,
but none alone satisfies the full request.

## File ownership and shared contracts

Create `backend/src/remind/` as the replacement package. Existing unfinished
`backend/tests/test_store.py` already targets this package and should
become real passing coverage, not be deleted merely to make collection pass.

| Files | Responsibility |
| --- | --- |
| `remind/config.py`, `contracts.py`, `database.py`, `models.py` | Settings, typed records, SQLite lifecycle/schema |
| `remind/memory/store.py`, `jobs.py`, `extraction.py`, `worker.py` | People/encounters, leases, evidence validation, orchestration |
| `remind/vision/models.py`, `quality.py`, `gallery.py`, `tracking.py`, `engine.py` | Model setup, quality, matching, association, frame processing |
| `remind/live/protocol.py`, `session.py`, `queues.py` | Binary framing, session ownership, bounded scheduling |
| `remind/audio/windows.py`, `media.py`, `speaker.py`, `providers.py` | VAD/windows, clip decoding, Light-ASD, cloud adapters |
| `remind/api.py`, `app.py`, `cli.py` | Local routes, lifespan, model setup and diagnostics |
| `remind/benchmark/manifest.py`, `metrics.py`, `replay.py`, `report.py` | Real-media replay and reports |
| `frontend/src/features/live/{protocol,capture,audio,session,geometry}.ts` | Browser media and session handling |
| `frontend/public/pcm-worklet.js` | AudioWorklet processor |
| `frontend/src/components/FaceOverlay.tsx` and existing pages | Camera UI, People, person correction/history |

All replacement Python subdirectories get `__init__.py`. Test fixtures inject
model/provider interfaces; integration tests use real temporary SQLite files.
Python identifiers below live in `remind/contracts.py` unless otherwise stated:

- `PersonRecord`, `PersonMemory`, `EncounterRecord`, `JobRecord`: TypedDicts with
  UUID-string IDs (patient ID is integer `1`), version integers and UTC times;
  `PersonMemory` includes nullable `last_encounter` and supported facts.
- `FramePacket`: generation, sequence, capture_ms, width, height, JPEG bytes.
- `FaceObservation`: normalized box, five landmarks, quality decision, optional
  normalized embedding. `TrackObservation`: track_id, person_id, state, box,
  last_seen_ms, identity_evidence_ms. State is observing/unknown/ambiguous/remembered.
- `VisionResult`: generation, sequence, capture_ms, source dimensions, tracks,
  changed memory cards and timings. No raw embeddings leave the backend.
- `SpeechWindow`: window_id, generation, start_ms, end_ms, PCM16 bytes,
  discontinuities. `MediaClip`: path, timeline anchors, duration, gaps.
- `TranscriptSegment`: id, start_ms, end_ms, request-scoped speaker, text.
- `SpeakerEvidence`: segment_id, track_id, score, coverage, conflicting flag.
- `ProposedFact`: subject person ID, predicate, value, evidence segment IDs,
  evidence quote, attribution status. `ExtractionResult`: facts and summary.
- `MemoryJobInput`: immutable encounter/participant snapshot, person versions,
  audio/clip paths and timeline anchors; never a pointer to a mutable live session.

`NDArray` is the NumPy typing alias. `IdentityMatch` is defined in `gallery.py`,
`Services` in `app.py` (store, vision engine, worker, model registry, session
manager), `AlignedMedia` in `audio/media.py`, and `BenchmarkReport` in
`benchmark/metrics.py`. `Settings` is defined in `config.py`. Each is owned by
the task that creates its file; avoid duplicate frontend/backend naming for
wire fields by testing shared JSON packet fixtures in both languages.

## Task 1: Durable patient-owned memory store

**Files:** Create `backend/src/remind/{__init__,config,contracts,database,models}.py`, `backend/src/remind/memory/{__init__,store,jobs}.py`; update `backend/pyproject.toml`, `backend/uv.lock`, `backend/.gitignore`; extend `backend/tests/test_store.py`; create `backend/tests/test_jobs.py`.

**Interfaces:** `Database(url: str)` has async `create_schema()` and `close()`.
`MemoryStore(db)` supplies the existing test's async methods: `ensure_patient`,
`create_person`, `get_person`, `list_people`, `start_encounter`, `add_participant`,
`close_encounter`, `person_memory`, `correct_person`, `forget_person`,
`enqueue_job`, `pending_jobs`. Add `claim_job(worker_id: str, now_ms: int) -> JobRecord | None`
and `finish_job(job_id: str, lease_token: str, result: ExtractionResult) -> bool`.

- [ ] Add a true close/reopen test (the existing reload test only reuses the same connection), concurrent singleton/enqueue tests, expired-lease retry, current-encounter exclusion, stale correction, and deletion-with-running-job cases. Assert patient ID `1`, one job per window key, and no deleted person after stale job completion.
- [ ] Run `cd backend && uv run pytest tests/test_store.py tests/test_jobs.py -q`; establish the expected missing-package/behavior failures.
- [ ] Add aiosqlite and implement schema with foreign keys, WAL, serialized short writes, unique job keys, leased jobs, UTC encounter ordering and optimistic versions. Store face templates as bounded float32 blobs with model ID; reject incompatible dimensions/models. Use a fresh `.local/remind.sqlite3`, leaving any old database untouched.
- [ ] Implement forget atomically: invalidate job leases/versions, remove templates/facts/thumbnail, and delete derived text/media for shared encounters that could still identify the person. Retain unrelated participant records without the deleted text. Add a cleanup ledger so failed filesystem deletions retry without restoring access.
- [ ] Repeat the focused tests; expect all pass, including actual disk persistence and stale-worker rejection.
- [ ] Review the task diff; create a scoped checkpoint commit if git writes are available, otherwise record the verified checkpoint without staging unrelated edits.

## Task 2: Installable, verified local vision models

**Files:** Create `remind/vision/{__init__,models,quality,engine}.py`, `remind/cli.py`, `backend/models/manifest.json`, `backend/models/licenses/`; update dependencies/lock; create `backend/tests/test_models.py`, `test_quality.py`.

**Interfaces:** `ModelRegistry.verify(model_id: str) -> Path`;
`OpenCVVision.detect(packet: FramePacket) -> list[FaceObservation]`;
`OpenCVVision.embed(image: NDArray, observation: FaceObservation) -> NDArray`.
CLI: `uv run python -m remind.cli models install` and `... doctor`.

- [ ] Write tests for missing/corrupt/wrong-size weights, malformed/oversized JPEGs, non-finite embeddings, and dark/blurred/tiny faces. Assert unusable faces cannot produce enrollment evidence.
- [ ] Run `uv run pytest tests/test_models.py tests/test_quality.py -q` from `backend`; expect missing implementation failures.
- [ ] Pin upstream model revisions, derive expected SHA-256 from upstream LFS metadata where available, retain licenses, and download atomically through the explicit install command. Never download during app startup. Add OpenCV-headless and warm YuNet/SFace with one owner, initial four-thread budget, aligned crops and normalized features.
- [ ] Implement `doctor` to report weight hashes, backend/device, SQLite access and provider configuration presence without printing keys. Explicitly distinguish CPU vision and CUDA speaker capabilities.
- [ ] Run focused tests plus install/doctor and a real-model image smoke test. Record load/inference timing; do not label it webcam fps or recognition accuracy.
- [ ] Review and checkpoint this task's files only.

## Task 3: Stable tracking, identity matching, and enrollment

**Files:** Create `remind/vision/{gallery,tracking}.py`; extend `engine.py` and store template methods; create `backend/tests/test_tracking.py`, `test_enrollment.py`.

**Interfaces:** `FaceGallery.match(embedding: NDArray) -> IdentityMatch` (person,
score, runner-up margin, ambiguous flag); `Tracker.update(observations, now_ms: float) -> list[TrackObservation]`;
`VisionEngine.process(packet: FramePacket) -> VisionResult` with serialized store
callbacks for enrollment and an immutable cached gallery snapshot.

- [ ] Add tests for crossing faces, near-tied different people, same-name people, bad-quality unknowns, transient passers-by, re-entry, and concurrent candidate enrollment. Assert no enrollment at 1999 ms or fewer than 5 usable observations; one person after eligible repeated evidence; no inherited name across ambiguous crossing.
- [ ] Run `uv run pytest tests/test_tracking.py tests/test_enrollment.py -q`; expect red cases.
- [ ] Implement one-to-one geometry/appearance association, identity invalidation on conflict, score+person-margin matching and temporal consensus. Aggregate templates by person before calculating the runner-up; cap at 8 diverse templates per person. Revalidate templates only on sustained strong matches. Configure score thresholds as uncalibrated defaults until Task 10.
- [ ] Add enrollment dwell and encounter-participation gates, serialized final-gallery recheck, and persistent provisional profiles. A sustained close silent encounter may qualify; mere detector presence must not. Share quality and identity gates between template updates and enrollment.
- [ ] Run tests and replay a real-model smoke clip with two people if an appropriate clip is available; report unavailable evidence explicitly.
- [ ] Review and checkpoint only these changes.

## Task 4: Live session service and bounded frame transport

**Files:** Create `remind/live/{__init__,protocol,queues,session}.py`, `remind/{api,app}.py`; create `backend/tests/test_protocol.py`, `test_session.py`.

**Interfaces:** `create_app(settings: Settings, services: Services | None = None) -> FastAPI`;
`LiveSession.accept_frame(packet: FramePacket) -> None`, async `stop() -> None`;
REST `/api/health`, `/api/session` (create owner), `/api/session/{generation}/stop`;
WebSockets `/api/live/{generation}/vision` and `/api/live/{generation}/audio`.
Binary packet = 4-byte big-endian JSON-header length + UTF-8 header + bytes;
header carries protocol version `1`, type, generation, sequence and media times.

- [ ] Test 100 queued frames during blocked inference: at most one running and one pending, latest pending survives, dropped count is correct. Test stale generation, malformed lengths, 4:3 dimensions, second capture owner, disconnect grace expiry, and an old job finishing after a new session starts.
- [ ] Run `uv run pytest tests/test_protocol.py tests/test_session.py -q`; expect missing-service failures.
- [ ] Implement dedicated vision executor, receive/compute/send task separation, bounded output, monotonic timing, per-person presence intervals, and cached memory cards. Generation-bound ownership tokens must cover both channels and uploads. Reject a second owner with a useful `409` response. Origin-check HTTP mutations and WebSockets; bind localhost.
- [ ] Cap header at 8 KiB and vision payload at 2 MiB; reject invalid dimensions/types before decode. Initial track display expiry 500 ms, participant absence grace 2 seconds, encounter close grace 8 seconds, owner heartbeat expiry 10 seconds. Keep these configurable and record them in benchmark metadata. Disconnect closes encounters durably; worker jobs survive.
- [ ] Run session/protocol tests with injected slow inference and provider stalls; assert vision continues without database/LLM work per rendered face.
- [ ] Review and checkpoint this service boundary.

## Task 5: Synchronized speech windows and audio-visual attribution

**Files:** Create `remind/audio/{__init__,windows,media,speaker}.py`, `remind/audio/light_asd/` (minimal licensed inference source), `backend/tests/test_audio.py`, `test_speaker.py`; extend model manifest/licenses and optional dependencies.

**Interfaces:** `AudioWindowBuffer.accept(pcm: bytes, start_ms: float, sample_rate: int) -> list[SpeechWindow]`, `flush() -> SpeechWindow | None`;
`decode_clip(clip: MediaClip) -> AlignedMedia`;
`SpeakerAttributor.score(media: AlignedMedia, tracks: list[TrackObservation], segments: list[TranscriptSegment]) -> list[SpeakerEvidence]`.
`AlignedMedia` defines 25 fps face clips, 16 kHz samples, valid-time mask and track IDs.

- [ ] Test speech shorter than an audio callback, trailing speech on Stop, 8-second cap, 300 ms pre-roll, audio gaps and sample-rate change. For attribution test visible silent person with off-screen speech, overlapping voices, missing clip frames, and incorrect AV offset. Assert these cases remain unresolved rather than choosing the sole visible person.
- [ ] Run `uv run pytest tests/test_audio.py tests/test_speaker.py -q`; expect missing adapter failures.
- [ ] Implement 20 ms VAD frames, 500 ms end silence, bounded pre-roll and explicit discontinuities. Decode clips with PyAV using media timestamps. Match clip faces to the live identity timeline through appearance+time; never use list order. Preserve valid-time masks when sampling the source at 25 fps.
- [ ] Adapt only Light-ASD inference/preprocessing from a pinned revision and checksummed weights; retain its license and source attribution. Do not import its whole batch demo or unconditionally call CUDA. Use `eval`, inference mode, explicit CPU/CUDA device, bounded inference batches and a separate executor. Match upstream outputs on a fixed clip before trusting the adapter.
- [ ] Gate each utterance on unique audio-visual support, coverage and conflict checks. Missing/low-quality media yields unassigned speech. Run focused tests plus real-weight CPU and CUDA smoke inference outside the sandbox when device access requires it. Record peak VRAM and time; accuracy remains for Task 10.
- [ ] Review and checkpoint the adapter with its measured limitations.

## Task 6: Evidence-backed cloud memory worker

**Files:** Create `remind/audio/providers.py`, `remind/memory/{extraction,worker}.py`; extend job store/API; create `backend/tests/test_extraction.py`, `test_worker.py`.

**Interfaces:** async `Transcriber.transcribe(window: SpeechWindow) -> list[TranscriptSegment]`;
async `Extractor.extract(segments: list[TranscriptSegment], allowed_subjects: dict[str, str]) -> ExtractionResult`;
`validate_extraction(result, segments, evidence) -> ExtractionResult`;
async `MemoryWorker.run_once() -> bool`. Upload endpoint
`POST /api/live/{generation}/clips` accepts bounded multipart clip + timeline metadata.

- [ ] Test introductions, negation, third-party statements, unassigned speaker labels, invalid evidence quotes, duplicate windows, stale corrections, forgotten participants, provider timeout/429, malformed output, and out-of-order completion. Assert no fact is accepted solely on LLM confidence; no duplicate or recreated person.
- [ ] Run `uv run pytest tests/test_extraction.py tests/test_worker.py -q`; establish failures.
- [ ] Implement diarized transcription and schema-constrained extraction using the existing provider account. Treat speaker labels as request-local; separate raw transcripts from accepted facts. Only pass evidence-backed person mappings to extraction; require actual supporting segments and exact normalized quote containment before commit. Quarantine conflicts and never estimate age from appearance.
- [ ] Persist immutable job inputs before acknowledgment. Limit worker concurrency to one initially, with 30-second provider deadlines, 3 attempts with backoff, lease renewal, and terminal failed status visible in the UI. Atomically commit accepted facts/summary/version and completion using the lease token. Do not replace manual fields or newer summaries with stale results.
- [ ] Implement 24-hour temporary-media expiry and 1 GiB local spool cap as configurable defaults; preserve transcript/source references for accepted facts. On full disk/spool, pause memory capture explicitly while vision continues. Add an optional patient voice-reference upload with duration validation and deletion support; never treat it as proof of visitor identity.
- [ ] Run focused tests plus a small real-provider smoke call only if credentials are configured; otherwise record the missing integration evidence. Review and checkpoint.

## Task 7: Browser camera, audio capture, and face-attached reminders

**Files:** Replace `frontend/src/features/live/live-session.ts`, `live-events.ts` with `protocol.ts`, `capture.ts`, `audio.ts`, `session.ts`, `geometry.ts`; create `frontend/public/pcm-worklet.js`, `frontend/src/components/FaceOverlay.tsx`; rewrite `LiveAssistantPage.tsx`; replace affected tests with `protocol.test.ts`, `session.test.ts`, `geometry.test.ts`, `LiveAssistantPage.test.tsx`.

**Interfaces:** `useLiveSession()` returns start/stop, stream, tracks, cards,
status, diagnostics. `encodePacket(header, bytes): ArrayBuffer` matches Task 4.
`mapBox(box, sourceSize, viewportSize, mirrored): ScreenBox` applies the same
object-fit transformation as video. Keep video aspect ratio intact.

- [ ] Test stale-generation and sequence rejection, denied media permission, asynchronous start cancelled by Stop, React StrictMode cleanup, second-tab `409`, reconnect, device changes and track expiry. Geometry tests cover 16:9/4:3, portrait viewport, letterbox and mirror. Assert devices and callbacks stop and no stale name remains on screen.
- [ ] Run `npm test -- src/features/live src/pages/LiveAssistantPage.test.tsx`; expect new behavior failures.
- [ ] Implement fresh-frame callback scheduling and asynchronous JPEG encoding, with one encode in flight and send backpressure. Video payloads carry actual encoded dimensions. Render video normally and boxes/cards above it; clamp cards to viewport, avoid covering faces, and limit text to supported identity and previous encounter.
- [ ] Implement AudioWorklet PCM capture/resampling and shared monotonic anchors. Capture separate bounded audio/video clips from the same stream for attribution using independently decodable MediaRecorder windows up to 8 seconds. Retain all chunks including each container header; do not upload arbitrary timeslice blobs as standalone files. Mark recorder restart gaps, delays and incomplete clips. Validate alignment against recorded audio, rather than assuming callback wall time equals media PTS. Deduplicate overlap by source window/time IDs.
- [ ] Bound clip uploads to one active/one pending, 16 MiB per clip; persist server receipt before dropping local copies. On overload suspend memory recording visibly, preserving vision. Flush final audio and clip, release devices immediately on Stop, then show pending save state. Keep diagnostic fps/latency out of the primary reminder cards.
- [ ] Run frontend tests/build/lint and browser fake-media capture tests including suspension and clock drift. Review and checkpoint.

## Task 8: People, supported facts, corrections, and forgetting

**Files:** Rewrite `frontend/src/pages/{PeoplePage,PersonDetailPage}.tsx`, `frontend/src/lib/{api,api-types}.ts`, `frontend/src/components/TopNav.tsx`, `frontend/src/App.tsx`; extend `remind/api.py`; replace related page/API tests and add `backend/tests/test_people_api.py`.

**Interfaces:** `GET /api/people`, `GET /api/people/{id}`, `PATCH /api/people/{id}`
with expected version, `DELETE /api/people/{id}`, `GET /api/jobs` (status only).
Person response includes thumbnail, supported fields, dated source facts and
encounter history. Correction conflict returns `409`; deleted person `404`.

- [ ] Test correction conflict and source display; forget while extraction runs; shared-encounter text removal; deletion invalidates an already-visible overlay; jobs cannot recreate erased data. UI tests assert errors are visible and retries are possible.
- [ ] Run `uv run pytest tests/test_people_api.py -q` and focused People/PersonDetail/API Vitest files; establish new-contract failures.
- [ ] Implement minimal People/detail UI, evidence inspection, correction and forget controls. Track manual ownership of corrected fields. Propagate memory-version invalidations to gallery and live cards without waiting for a page reload. Keep only Live and People in navigation.
- [ ] Verify API tests and frontend tests/build/lint; inspect real browser layout at laptop and narrow viewport sizes.
- [ ] Review and checkpoint only the feature files and tests.

## Task 9: Cut over and remove obsolete application code

**Files:** Remove old `backend/src/{api,core,db,providers,realtime,schemas,services}/`, `backend/src/main.py`, obsolete `backend/migrations/`, `backend/alembic.ini`, old backend unit/integration tests after mapping their still-relevant behaviors; remove `frontend/src/pages/ProfilePage.tsx`, its test, obsolete live files/tests, unused assets/components/hooks. Update both dependency manifests/locks, env examples, READMEs and API docs; add root `README.md`.

**Interfaces:** Launch `uv run uvicorn remind.app:app --host 127.0.0.1 --port 8000`;
frontend uses Vite dev proxy for `/api` HTTP/WebSocket traffic. Only the new
contract is exposed; no compatibility adapter or Postgres startup requirement.

- [ ] Add full integration test `backend/tests/test_memory_loop.py`: enroll unnamed visitor, save attributed introduction/fact, close encounter, reopen the real SQLite file with new services, recognize return, fetch correct previous memory. Add missing-model and missing-key startup/readiness cases.
- [ ] Run that test against the integrated replacement and confirm meaningful assertions fail before completing missing wiring.
- [ ] Wire app lifespan, model load, gallery initialization, worker recovery and shutdown; ensure startup remains usable for People when models or cloud credentials are unavailable, with explicit capability status. Replace launch/proxy settings and remove old runtime/tests/dependencies only after the new integration test passes.
- [ ] Document model installation, dependency groups, local launch, OpenAI key placement, CPU/GPU capability checks, new schema location, supported inputs, deletion behavior, cloud use and error recovery. Do not tell users to delete an existing Postgres database.
- [ ] Run `uv run pytest`, `uv run ruff check .`, `uv run mypy src/remind`; run `npm test`, `npm run build`, `npm run lint`. Search for obsolete service references and broken documentation links. Expect all checks pass or document an actual blocking failure without concealing it.
- [ ] Review deletion diff carefully and checkpoint the cutover.

## Task 10: Benchmark tooling, calibration, and measured acceptance

**Files:** Create `remind/benchmark/{__init__,manifest,metrics,replay,report}.py`, `backend/tests/test_benchmark.py`, `frontend/e2e/memory-loop.spec.ts`, `frontend/playwright.config.ts`, `benchmarks/manifest.example.json`, `benchmarks/README.md`; update evaluation document with actual report links and `docs/testing/reports/` with sanitized reports.

**Interfaces:** CLI `uv run python -m remind.cli benchmark MANIFEST --output DIR`
supports `--mode realtime|throughput`; `--models fake|real` is explicit and
recorded. `evaluate_trace(events: Iterable[dict], truth: dict) -> BenchmarkReport`
reports denominators, percentiles, coverage, failures and insufficient evidence.
Manifest defines video/audio paths and hashes, identities/gallery split,
timelines, boxes, speakers, facts, scenarios and immutable configuration.

- [ ] Test metrics against hand-calculated traces with duplicate/interpolated frames, 10-second windows below target, false unknown/known matches, no accepted facts, zero eligible cases and different clock domains. Assert no divide-by-zero and no success claim for empty data or fake models.
- [ ] Run `uv run pytest tests/test_benchmark.py -q`; establish failures, then implement the three-runner protocol and JSON/JSONL/Markdown reports from the approved evaluation document. Emit all configured thresholds/model checksums and exact device metadata.
- [ ] Implement recorded-rate replay and independently labeled gallery/probe evaluation. Add a scripted browser restart flow with injected provider outputs, explicitly labeled a logic test. For real accuracy runs require real weights, media, labels and provider configuration; do not generate fake accuracy numbers from synthetic fixtures.
- [ ] Calibrate only on development recordings; freeze operating thresholds before held-out tests. Measure CPU vision concurrently with CPU/CUDA speaker analysis and compare modes on this i7/RTX 2050. Record peak VRAM, thermals, cloud cost, dropped frames and end-to-end age. Test 30 minutes at 1–3 faces, gallery 500; evaluate 5 faces/1000 people as stress conditions.
- [ ] Check all gates: ≥10 fresh fps in ≥95% of 10-second windows; p95 result age ≤250 ms; p95 identity latency ≤1 s; returning-person coverage ≥95%; enrollment ≥95%, duplicates ≤2%; accepted-fact attribution ≥99% with clean-case coverage ≥80%; fact precision ≥98%; p95 memory latency ≤15 s. Report the unknown-error target ≤0.1% with confidence bounds and insufficient evidence if trial count cannot support it. No named identity swaps in scripted crossings, and all persistence/correction/forget invariants pass.
- [ ] If any gate fails, use traces to change the responsible component and rerun the affected test/benchmark. If SFace's accuracy gate fails despite calibration, compare a suitably licensed replacement under the same protocol; do not silently trade correctness for fps. If real recordings/credentials are absent, finish tooling and available tests but leave real-world acceptance explicitly outstanding.
- [ ] Complete the selected execution workflow's final review, fix findings, rerun relevant checks, and provide the measured report, setup still needed and limitations. Do not mark the overall rewrite complete solely because unit tests pass.

## Plan self-review

- Scope coverage: Tasks 1/6/8 own persistent memory and ownership; 2/3 own vision;
  4/7 own real-time transport/UI; 5/6 own attribution; 9 owns removal; 10 owns
  performance/accuracy evidence. No required attribution work is deferred out
  of the definition of completion.
- Interfaces: shared timebases, generation IDs, immutable job snapshots, person
  versions and lease tokens connect tasks explicitly. All method-only types are
  defined in their owning files or the shared contracts list.
- Review Focus: each of the five conditions has a named owning test step.
- Hardware: GPU available, but accelerated framework installation and actual
  measurements remain implementation tasks. No 10 fps guarantee is inferred
  from the laptop specification.
- Execution status: no product code, dependencies or models changed during
  plan preparation. User subsequently approved the plan and selected direct implementation here.
