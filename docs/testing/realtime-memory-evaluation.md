# One-on-one memory evaluation

The first validation milestone uses automated fixtures. Measure the entire chain:
face identity → capture-time visitor → user/visitor/uncertain speech roles →
supported subject-specific facts → consolidation → persistence → returning reminder.

## Automated checks

- Voice: three distinct enrollment samples; separate same-user and different-person
  test speech; silence, too-short audio, clipping, overlap, inconsistent samples,
  uncertain scores, corrupt assets and unavailable dependencies.
- Media: bounded audio-only decoding of WAV/WebM, resampling, timestamp gaps,
  malformed files and maximum duration. No speaking-face/video inference.
- Dialogue: natural introductions, names after questions, visitor confirmations,
  cross-clip context, label changes, unconfirmed question premises, third-party
  subjects, negations, hypotheticals and fabricated evidence.
- Memory: compatible interests accumulate, repeated evidence deduplicates, explicit
  changes/corrections retain history, unexplained contradictions stay unresolved,
  plans do not auto-complete, manual corrections and dismissals take precedence.
- Association: stable one visitor, unknown/second face, identity changes, expired
  timeline and jobs delayed until another person arrives.
- Lifecycle: idempotent retries, restart recovery, edits/forgetting/voice-reference
  replacement while processing, data persistence and live cache refresh.
- Browser: helper enrollment, automatic visitor encounter, detailed memory,
  stop/reload/return, source inspection, correction, forgetting and voice removal.
  Use desktop and mobile sizes; inspect console errors and screenshots.

Run backend pytest/Ruff/mypy and frontend Vitest/build/ESLint, then Playwright.
Browser plugin is absent in this environment; regular Playwright is the fallback.
Screenshots and transient reports belong under /tmp, not committed source.

## Metrics and interpretation

Report separately:

| Metric | Definition |
| --- | --- |
| Fact correctness | Adjudicated supported facts / all established facts |
| Subject correctness | Facts attached to the expected subject / accepted facts |
| Useful-fact coverage | Supported expected facts saved / eligible expected facts |
| Processing latency | Clip/utterance completion to durable memory; show stage timings |
| Role decisions | User/visitor correctness and uncertain coverage on held-out speech |
| Recovery | Duplicate writes, stale writes, missing sources after lifecycle tests |

Fixture assertions provide deterministic expected outcomes, never percentages for
real-world conversations. Public-audio ECAPA smokes must use different utterances
for enrollment and verification and identify their source/model revisions.
Synthetic voice or mocked providers cannot establish recognition or semantic
accuracy. Report missing real-model runs instead of counting them as passes.

## Later staged evaluation

Record English one-on-one introductions and return encounters on the actual
camera/microphone. Separate enrollment, development/calibration, and held-out
recordings by session, ideally by day. Include natural answers, corrections,
relatives, past jobs, future plans, brief face loss, background voices and overlap.

Freeze thresholds before held-out evaluation. Report precision together with
coverage and latency, so rejecting everything cannot appear successful. Clearly
identify wrong-user/visitor assignments and wrong subjects. In this MVP, a
television or off-screen voice may be assumed to be the visitor; test and report
that limitation. No patient-use accuracy or sustained performance claim follows
from fixture or component smoke results.
