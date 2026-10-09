# Remind evaluation strategy

Date: 2026-10-08; implementation update: 2026-10-09. The scenario matrix and
acceptance gates below remain the evaluation protocol. Logic tests, component
smokes and a short browser timing run are implemented; see the
[implementation measurements](reports/2026-10-09-implementation.md). Held-out
recognition/speaker accuracy and full sustained acceptance are still unmeasured.

## What must be measured

Evaluate the full chain: detect → track → identify or enroll → associate speech
→ extract facts → persist → recall on a later encounter. A fast preview or high
pairwise face-verification score is not evidence that this chain works.

Record exact machine, OS, browser, power mode, camera, microphone, input sizes,
model checksums, library versions, thread counts, configuration, gallery size,
network conditions, and commit/worktree diff identifier with every run. Report
CPU, GPU, RAM, disk, thermal slowdown, and cloud audio/token cost per hour.

## Three complementary runners

1. Deterministic integration runner: synthetic detections and fixed provider
   responses exercise state transitions, storage, retries, stale results,
   crossing/identity conflicts, and corrections. It establishes correctness of
   logic, never model accuracy or camera throughput.
2. Recorded-media runner: timestamped video/audio, face/identity annotations,
   speaker truth, and expected facts pass through real model adapters. Replay at
   the original wall-clock rate to expose queueing and drops. A separate
   unthrottled run measures maximum throughput; do not confuse the two results.
3. Browser end-to-end runner: feed a known camera/microphone recording through
   browser capture, transport, overlay rendering, and persistence. Include a
   real-device session to catch camera exposure, audio resampling, permission,
   browser scheduling, and thermals that prerecorded input misses.

Each runner emits machine-readable JSON metrics, per-event JSONL traces, and a
short Markdown report. Optional annotated video helps inspect swaps and stale
boxes. Benchmark tooling uses an isolated disposable data directory, never the
patient's live gallery. Synthetic smoke fixtures are explicitly labeled.

## Dataset and split

Start with a debugging pilot of 10–20 consenting adult participants recorded in
separate enrollment and return sessions, preferably on different days. Include
older adults and the actual camera geometry as data becomes available; a
young-adult laptop dataset alone does not establish suitability for the patient.
Do not infer demographic annotations from faces.

Use identity-disjoint development and held-out evaluation groups. Within each
group, separate enrollment from return sessions by recording, time, and camera
conditions. Never split neighboring frames from one clip between calibration
and test. Unknown evaluation people must have no templates in the gallery.
Freeze matching thresholds, top-two margin, temporal rules, enrollment quality
gates, and attribution thresholds before opening the held-out test results.

For each scenario record:

- Media path, SHA-256, frame/audio timebase, and scenario labels.
- Ground-truth face boxes and person IDs; sampled annotations plus event-dense
  labels around crossings, exits, and re-entry.
- Enrollment eligibility, existing gallery state, and encounter boundaries.
- Word/utterance transcript, speaker ID, face visibility and overlap intervals.
- Supported facts, exact evidence span, correct subject, and deliberately
  unanswerable questions. Distinguish absence of evidence from false facts.
- Expected previous encounter for each returning person.

Manually adjudicate fact/subject labels independently of the extracting model.
Use a second annotator for ambiguous examples; report unresolved labels rather
than choosing truth based on the system output.

## Scenario matrix

| Dimension | Cases |
| --- | --- |
| Visibility | Frontal, moderate/extreme yaw, looking down, partial occlusion, glasses, mask |
| Lighting | Normal indoor, dim, backlight, uneven exposure, changing light |
| Scale and motion | Near/far faces, small crops, walking, head turn, camera movement, blur |
| People | 0/1/2/3/5 faces, lookalikes, same name, known+unknown, crossings, leave/re-enter |
| Enrollment | Short passer-by, sustained interaction, unnamed person, poor-quality first view, repeated new tracks |
| Audio | Quiet/noisy, patient speaks, visitor speaks, off-screen speech, television, overlap, long silence |
| Meaning | Self-introduction, introducing someone else, negation, correction, joke, uncertain date, conflicting relationship |
| Lifecycle | Stop mid-utterance, tab close, reconnect, restart, two live tabs, delayed/out-of-order jobs |
| Faults | Missing weights, provider timeout/429/error, malformed output, invalid evidence, disk limit, 30-second network outage |
| Ownership | Edit during extraction, forget during extraction, cache invalidation, shared-encounter removal |
| Load | Gallery 10/100/500/1000 people, sustained 30-minute capture, pending cloud jobs |

Use English conversations with diverse accents. A scripted example: visitor
introduces themselves as Anna, says they are the patient's daughter, and mentions
Sunday lunch. Later Anna returns beside Ben. The card must attach to Anna,
include only supported facts, and describe the earlier encounter. Include
"Anna is my sister" spoken by Ben and "I'm not your daughter" as counterexamples.

## Metrics and proposed acceptance gates

These are engineering targets for an initial useful version, not measured
claims or a clinical validation standard. Report numerator, denominator, and
95% confidence intervals alongside rates. Accuracy and coverage must be shown
together: abstaining on every case cannot pass.

| Area | Metric | Initial gate under baseline conditions |
| --- | --- | --- |
| Fresh vision | Completed distinct detector/tracker frames per second | ≥10 in at least 95% of non-overlapping 10-second windows over 30 minutes, 1–3 faces |
| Latency | Capture-to-painted-result age | p95 ≤250 ms; record p50/p95/p99/max |
| Recognition | First eligible face observation to stable correct identity | p95 ≤1 second for enrolled, usable faces |
| Open-set identity | Unknown encounters receiving a known identity | Target ≤0.1%; report uncertainty and also known-person wrong matches |
| Recognition coverage | Eligible returning encounters correctly identified within 2 seconds | ≥95% in baseline lighting/pose conditions |
| Enrollment | Eligible new-person encounters enrolled without merging with another person | ≥95%; duplicate-person rate ≤2% |
| Tracking | Named identity switches | Zero in the scripted crossing suite; also report switches per 100 track-minutes |
| Attribution | Correct subject among accepted personal facts | ≥99%, with supported-fact coverage ≥80% in clean visible-speaker cases |
| Fact extraction | Supported and correct facts among saved facts | ≥98%; separately report name/relationship/age accuracy |
| Recall | Correct previous encounter attached to the correct person | 100% in deterministic integration cases; report real-media rate |
| Memory latency | Utterance end to durable accepted memory | p95 ≤15 seconds on a healthy provider connection |
| Recovery | Idempotent jobs, restart persistence, correction/forget protection | All specified deterministic cases pass |

Define "eligible" before testing using annotated face quality/visibility and
encounter duration, not whether the model happened to succeed. Also report
unconditional performance on all encounters and challenge subsets. Quiet,
fully occluded, off-screen, or genuinely ambiguous cases are expected to abstain
from unsupported personal facts; measure those false attributions separately.

The 0.1% identity target needs substantially more evidence than a small pilot.
With zero observed errors, roughly 3,000 independent unknown trials are needed
for a one-sided 95% binomial upper bound near 0.1% (rule-of-three approximation).
Adjacent video frames are not independent trials. Cluster confidence intervals
by person/session where appropriate. A small pilot can support development,
but must be reported as insufficient evidence for that target.

Track false positive identification and missed identification separately, as in
[NIST's identification evaluation](https://www.nist.gov/publications/face-recognition-vendor-test-frvt-part-2-identification).
Also measure wrong-known-person identification, since an unknown-only metric
misses errors between enrolled people. Report difficult conditions separately;
do not let an easy majority conceal failure on dim light or older faces.

## Instrumentation details

Use session generation + frame sequence and browser monotonic capture time to
join capture, encode, send, receive, inference, result, and painted-overlay
events. Return the original browser timestamp to measure end-to-end age in the
same clock domain. Measure backend stages on its own monotonic clock; never
subtract unsynchronized browser and server clocks. Record final audio-sample
time, VAD flush, transcription completion, attribution completion, extraction,
and committed memory version to explain memory latency.

Separate preview fps, captured/sent fps, received fps, processed fresh fps,
embedding evaluations per second, painted new results, dropped frames, and
stale-result rejections. Include an overloaded run proving queues remain
bounded and display age recovers after load is removed. Do not count interpolated
boxes as fresh detections or a 30 fps video element as 30 fps recognition.

Measure box overlap against annotations and actual screen alignment after
letterboxing/cropping/mirroring. Test 16:9 and 4:3 cameras and narrow screens.
Timestamp correctness matters to both the overlay and speaker attribution.

## Calibration, comparison, and completion

Sweep score threshold, per-person template count, ambiguity margin, input
resolution, and temporal consensus on development sessions. Compare SFace and
any licensed replacement using the same gallery and test clips. Prefer the
fastest configuration that meets the identity error and coverage gates.

Run ablations: single frame versus temporal evidence; one template versus a
diverse gallery; geometry-only versus appearance-assisted tracking; no speaker
link versus audio-visual attribution. Each extra component must show a measurable
benefit to the main memory flow. Log dropped frames and CPU contention when
audio-visual analysis and cloud job handling run together.

Completion requires passing logic/integration tests, a measured real-model
report on named hardware, a browser flow demonstration across process restart,
and a documented list of unsupported conditions. If models, credentials,
hardware, or labeled recordings are unavailable, report the missing evidence
explicitly. Mock-provider tests must never be presented as proof of live accuracy.
