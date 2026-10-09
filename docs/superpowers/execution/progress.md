# Execution ledger — plan: docs/superpowers/plans/2026-10-08-realtime-memory.md

User approved design and plan; requested direct implementation in this checkout.
Baseline: dirty checkout, frontend 43 passing; backend collection fails on missing remind package.
Ruling: work in place and retain uncommitted checkpoints — explicitly requested; git metadata read-only; cost: no isolated branch checkpoints.
Preflight: Tasks 1/3/6/8 share person versions and template invalidation; use database revision to invalidate gallery/cards.
Preflight: Tasks 4/5/7 share generation plus monotonic media milliseconds; all job inputs snapshot the original generation and presence intervals.
Preflight: Tasks 1/6 use tokenized leases; corrections/forget invalidate pending work at commit.
Preflight: Tasks 2/5/10 share pinned model identities; unavailable models never count as real-model acceptance.
Initial Task 1 checkpoint; current task outcomes are recorded below.
Ruling: use direct aiosqlite SQL for the compact schema rather than add an ORM layer — explicit transactions make leases/version checks inspectable; cost: hand-maintained SQL.
Storage/vision/session/extraction checks: 19 tests passing (uv run --extra speaker pytest tests -q, 2026-10-09). Full task acceptance remains in progress.
Ruling: memory uses audio decoded from the same independently decodable WebM clip as speaker video, rather than a second AudioWorklet stream — avoids cross-stream clock drift and preserves 16 kHz resampling in PyAV; cost: memory waits for bounded clip finalization.
Ruling: CPU PyTorch is installed first to avoid multi-GB CUDA dependencies; CUDA remains an explicit runtime option after compatible installation. Cost: speaker inference may miss the latency budget on CPU; benchmark separately.
Real model smoke: verified all three pinned checksums; one-face CPU YuNet+SFace mean 23.73 ms, p95 37.95 ms over 50 repeated-image frames (not a real-world accuracy/latency benchmark). Light-ASD CPU returned finite 24-frame scores in 0.408 s for a one-second synthetic input.
Browser plugin not available; regular Playwright selected. Browser test backend uses an isolated .local/e2e store and disables cloud calls.
Recovery regression: exhausted crashed lease observed stuck running; fixed to terminal failed state. Existing correction and forget tests protect delayed writes.

## Implementation checkpoint — 2026-10-09

The approved rewrite was executed directly in this checkout. No commit, reset,
or migration of legacy patient data was performed. Existing unrelated dirty
work was preserved; replaced runtime paths and obsolete features were removed.

| Plan area | Delivered | Outstanding evidence/adjustments |
| --- | --- | --- |
| 1. Memory store | SQLite single patient, bounded templates, encounters, sources, corrections, forget, leased/idempotent jobs, actual reopen tests | SQL used directly rather than ORM; types are partly inferred |
| 2. Local models | Pinned YuNet/SFace/Light-ASD weights, checksums, licenses, installer/doctor, CPU model smoke | CUDA smoke/comparison not performed |
| 3. Recognition | Quality gates, normalized gallery match/margin, appearance-assisted tracks, repeated agreement, bounded auto-enrollment | Operating thresholds and real-world duplicate/error rates uncalibrated |
| 4. Live transport | Single owner, generation/sequence timestamps, latest-only frame queue, independent expiry watchdog, stale-result rejection | Browser reconnect is explicit Start again |
| 5. Speech/attribution | Synchronized WebM, PCM resampling, silence VAD, PTS/format checks, local Light-ASD, immutable identity timeline/full gallery, overlap abstention | Reference-output equivalence and labeled active-speaker accuracy pending |
| 6. Memory worker | Real diarized transcription and structured extraction, direct-statement/evidence validation, cumulative summary context, retry/renewed leases, storage limits/expiry | Optional patient voice reference omitted; richer statements kept in summaries |
| 7. Live interface | Camera/face reminders, previous encounter, device cleanup, upload pause/retry/download, job retry, diagnostics/timing export | Bounded eight-second clips with upload gaps, not continuously streamed speech |
| 8. People | List/detail, evidence/history, changed-field corrections, forget including shared derived profile text | No caregiver or multi-patient flow |
| 9. Removal | Old API/service/ORM/migrations, deployment containers, profile/graph/search surfaces and unused UI dependencies removed | Legacy `.local` data retained |
| 10. Evaluation | Deterministic restart integration; real component replay; browser flow and timing export; adjudicated trace metrics; JSON/JSONL/Markdown reports; scenario/calibration protocol | Full 30-minute acceptance and labeled accuracy cannot be established without recordings |

Ruling: retain all competing gallery identities during clip analysis and require
matching captured live evidence. Cost: more abstention when live frames are
missing; benefit: delayed jobs cannot silently relabel a visitor.
Ruling: direct English self-statements are required for automatic profile fields.
Cost: lower coverage than free paraphrase; unsupported values stay unaccepted.
Ruling: mixed-encounter/expired-timeline clips abstain from assignment rather
than selecting a current encounter. Cost: those boundary clips do not create memory.
Ruling: one failed upload remains in browser memory with retry/download; capture
pauses. Cost: it does not survive closing the tab without downloading.
Ruling: no optional patient voice reference yet; off-screen/ambiguous speech is
unassigned. Cost: reduced subject coverage; no face identity inferred from voice alone.
Ruling: original checklist is preserved as the acceptance target; this ledger
records delivered implementation and honest limitations rather than marking
unmeasured accuracy/performance steps complete.

Independent final review: eight important findings, no critical findings reported.
Implemented fixes with failing regression reproductions; see the
[measurement/review report](../../testing/reports/2026-10-09-implementation.md).
Latest verification: 37 backend tests, 6 frontend tests, 2 Chromium flow/trace tests;
Ruff, configured mypy, ESLint and production build pass. All three model hashes
verified. Existing OpenAI key successfully exercised transcription and extraction.
The short one-face browser workload sustained 25 fresh fps with an 85 ms p95
capture-to-display bound; this is not full acceptance.

Three-face component workload: 749 processed frames in 30.11 s, p95 processing
28.20 ms; all 749 had three usable faces. Uses repeated cropped public imagery
and an empty gallery; cloud idle. A prior lossy fixture was rejected as a stable
three-face workload. No production thresholds changed for the fixture.

Stop/upload regression: reproduced a retained final clip receiving 409 after Stop;
completed-session uploads now retain their generation capability for two minutes,
without reopening the camera owner. Verified by the API regression test.
