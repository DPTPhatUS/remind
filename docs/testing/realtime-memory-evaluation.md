# Evaluating Remind

Use the [four benchmark commands](../../benchmarks/README.md) to measure different
failure sources independently:

1. **Audio → roles:** real transcription/diarization and local user-voice matching.
2. **Conversation → facts:** supplied transcript roles through extraction,
   verification, evidence validation and saved-memory consolidation.
3. **Face:** automatic enrollment and recognition through the normal live backend.
4. **Video/audio → facts:** source-timed input through the complete backend chain.

Expected labels stay in scoring. Conversation text/roles are deliberately supplied
component inputs; face associations and voice references are never fabricated by
the video benchmark. Use independent enrollment/test passages and freeze source
hashes, settings and annotations before inference.

Report role errors, uncertainty and missed speech separately; face association
coverage alongside wrong matches; and supported fact coverage alongside subject,
evidence and historical-state errors. Exact unmatched wording needs evidence
review. State sample counts, source quality, repeated recordings, incomplete
annotations and unmeasured stages. Empty output never establishes accuracy.

Ordinary application tests cover restart recovery, retry idempotency, manual
corrections, forgetting and voice replacement during pending work, capture-time
visitor changes, multiple faces, invalid evidence and browser behavior. These
regression tests establish software behavior, not model accuracy.

Run backend pytest, Ruff and mypy; frontend Vitest, build and ESLint; and the
remaining Playwright application suite. The benchmark guide documents commands,
current inputs and report formats. Physical microphone/camera quality, background
voices under the one-on-one assumption, broader populations and use by people
with memory impairments require separate real-device evaluation.
