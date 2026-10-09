import numpy as np

from remind.audio.speaker import assign_speakers
from remind.audio.windows import AudioWindowBuffer


def test_final_partial_and_eight_second_limit():
    buffer = AudioWindowBuffer(is_speech=lambda _: True)
    data = np.ones(16000 * 9, dtype=np.int16).tobytes()
    windows = buffer.accept(data, 0, 16000)
    assert len(windows) == 1
    assert len(windows[0]["pcm"]) == 16000 * 8 * 2
    last = buffer.flush()
    assert len(last["pcm"]) == 16000 * 2


def test_offscreen_and_overlapping_speaker_abstain():
    segments = [{"id": "s", "speaker": "A", "start_ms": 0, "end_ms": 1000}]
    assert assign_speakers(segments, []) == {}
    evidence = [
        {"segment_id": "s", "person_id": "p", "score": 0.95, "coverage": 1},
        {"segment_id": "s", "person_id": "q", "score": 0.94, "coverage": 1},
    ]
    assert assign_speakers(segments, evidence) == {}
    assert assign_speakers(segments, evidence[:1]) == {"A": "p"}


def test_overlapping_or_multiple_speakers_cannot_map_to_same_person():
    segments = [
        {"id": "a", "speaker": "A", "start_ms": 0, "end_ms": 1000},
        {"id": "b", "speaker": "B", "start_ms": 500, "end_ms": 1500},
    ]
    evidence = [
        {"segment_id": sid, "person_id": "p", "score": 0.95, "coverage": 1} for sid in ("a", "b")
    ]
    assert assign_speakers(segments, evidence) == {}


def test_audio_timestamp_gaps_and_format_changes_abstain():
    from remind.audio.media import audio_is_continuous

    assert audio_is_continuous([(0, 0.02, 48000, "stereo"), (0.02, 0.02, 48000, "stereo")])
    assert not audio_is_continuous([(0, 0.02, 48000, "stereo"), (0.12, 0.02, 48000, "stereo")])
    assert not audio_is_continuous([(0, 0.02, 48000, "stereo"), (0.02, 0.02, 16000, "mono")])


def test_clip_attribution_needs_same_live_identity_and_geometry():
    from remind.audio.speaker import timeline_supports

    timeline = [{"ms": 1000, "people": [{"person_id": "p", "box": [0.1, 0.1, 0.2, 0.3]}]}]
    assert timeline_supports(timeline, 1050, "p", [0.1, 0.1, 0.2, 0.3])
    assert not timeline_supports(timeline, 1050, "q", [0.1, 0.1, 0.2, 0.3])
    assert not timeline_supports(timeline, 1400, "p", [0.1, 0.1, 0.2, 0.3])
    assert not timeline_supports(timeline, 1050, "p", [0.7, 0.1, 0.2, 0.3])
