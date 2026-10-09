# Implementation measurements — 2026-10-09

The rewrite is implemented in the working tree. **Full acceptance is not yet
established.** No held-out participant recordings were available. The results
below test engineering behavior and short workloads, not patient-use accuracy.

Machine inspected: Intel Core i7-1360P, approximately 16 GB RAM, RTX 2050 with
4 GB VRAM. Runtime measurements here use CPU OpenCV 5.0 and CPU PyTorch 2.14.1;
CUDA was not used. The driver sees the GPU, but the installed CPU PyTorch wheel
does not expose CUDA. All YuNet, SFace and Light-ASD weight hashes were verified.

| Check | Observed result | Scope |
| --- | --- | --- |
| Backend suite | 37 passing tests | Temporary SQLite, store/lease/recovery, identity, attribution, protocol, benchmark logic |
| Frontend suite | 6 passing tests | Routes, people loading, stale frames and upload retry |
| Build and static checks | Vite/TypeScript build, ESLint, Ruff, configured mypy pass | Mypy is permissive; many Python function bodies are untyped |
| Browser flow | 2 passing Chromium tests | Real face models, fake camera, enroll/correct/stop/return/forget, timing export |
| One-face component replay | 200 frames in 6.54 s including startup; p95 processing 37.13 ms | Static public image video; empty gallery, cloud idle |
| Three-face component replay | 749 distinct frames in 30.11 s; p95 processing 28.20 ms | Three repeated cropped faces, 749/749 frames had three usable faces; empty gallery, cloud idle |
| Browser fresh-result run | 431 frames over 17.20 s, 25.00 fps | One static face, fake camera, cloud disabled |
| Browser display timing | p50 66.4 ms, p95 85.05 ms, p99 92.57 ms, max 115.8 ms | Two-animation-frame upper bound after result receipt; browser clock only |
| Audio/video decoding | 200 video frames and 8 s PCM; synchronization checks passed | Synthetic fixture with public speech audio |
| Real transcription API | 2 timestamped segments, 1 speaker label, 4.25 s | Eight-second public OpenAI Whisper test audio; existing account/key |
| Real structured extraction API | Supported name and relationship accepted | Synthetic introduction text, supplied subject mapping |
| Light-ASD model smoke | 24 finite frame scores in 0.408 s | One-second synthetic input; no attribution-accuracy claim |
| Full memory logic | Introduction → durable facts → DB close/reopen → returning-person reminder passes | Injected provider/media/speaker outputs; real store/session code |

Raw component and browser metric summaries:
[component JSON](2026-10-09-vision-throughput.json),
[browser JSON](2026-10-09-browser-smoke.json),
[three-face component JSON](2026-10-09-three-face-component.json).
Per-event traces and the public fixtures remain under ignored `backend/.local`.
The browser source fixture is OpenCV's public Lena test image; it supplies a
stable test face and no evidence about real-world enrollment/recognition.
The three-face fixture is losslessly encoded to keep the workload stable. An
earlier lossy fixture passed the three-usable-face check on only 250/750 frames
and was rejected as a sustained three-face workload. No production thresholds
were changed to improve this fixture.
The speech fixture is [`openai/whisper/tests/jfk.flac`](https://github.com/openai/whisper/tree/main/tests).
The cloud adapter follows the [official transcription API](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create).

## Review and regression coverage

A read-only independent review found eight important issues. Fixes now cover:
original encounter selection for delayed clips; forget invalidation including
late uploads and shared derived profile fields; immutable live timeline and
full-gallery checks for speaker attribution; abstention on overlapping or
conflicting speaker assignments; audio PTS/format continuity; bounded retained
uploads with retry/download; direct support for profile values; and an owner
watchdog independent of cloud work. Additional fixes protect stale browser
starts, manual-field ownership and failed-job recovery. Each substantive
regression was reproduced before fixing it.

## Remaining evidence and implementation limits

- The 30-minute 1–3-person/500-person-gallery run with concurrent memory work
  has not been performed. Neither have CUDA comparisons or thermal/cost runs.
- Recognition error, duplicate enrollment, active-speaker attribution, fact
  precision/coverage and full utterance-to-memory latency need independently
  labeled development and held-out recordings. No accuracy percentage is claimed.
- Light-ASD loads and runs, but reference-pipeline equivalence and its operating
  threshold have not been validated on a labeled speaking-face clip.
- Direct-statement validation intentionally accepts a narrow set of English
  forms. Summaries support richer conversation content, but remain model outputs.
- Capture uses independently decodable clips up to eight seconds. It pauses
  briefly while a clip uploads; interruptions can split statements. VAD skips
  silent clips on the server rather than driving browser clip boundaries.
- Clips spanning two distinct encounters, clips without stable participants,
  or clips delayed beyond the retained two-minute timeline are not assigned.
  Discontinuous media can produce summaries but cannot assign personal facts.
- A failed upload is retained in browser memory, not persisted across tab close.
  Retry or download it before leaving. Final-clip retries remain accepted for
  two minutes after Stop, until a new session replaces the capture owner. Forgetting ends the active capture owner
  and invalidates affected shared encounters; restart capture afterward.
- Optional patient voice-reference enrollment is not implemented. Off-screen
  speech remains unassigned unless supported by visible-speaker evidence.

Follow [the benchmark instructions](../../../benchmarks/README.md) and
[the evaluation protocol](../realtime-memory-evaluation.md) for the release gates.
