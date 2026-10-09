import uuid
from collections import deque


class AudioWindowBuffer:
    def __init__(self, is_speech=None):
        if is_speech is None:
            import webrtcvad

            vad = webrtcvad.Vad(2)

            def is_speech(pcm):
                return vad.is_speech(pcm, 16000)

        self.is_speech = is_speech
        self.pending = b""
        self.active = bytearray()
        self.pre = deque(maxlen=15)
        self.silence = 0
        self.cursor = None
        self.started = 0

    def accept(self, pcm, start_ms, sample_rate):
        if sample_rate != 16000 or len(pcm) % 2:
            raise ValueError("Expected mono 16 kHz PCM16")
        if self.cursor is not None and abs(start_ms - (self.cursor + len(self.pending) / 32)) > 60:
            self.active.clear()
            self.pending = b""
            self.pre.clear()
            self.cursor = start_ms
        if self.cursor is None:
            self.cursor = start_ms
        self.pending += pcm
        windows = []
        while len(self.pending) >= 640:
            frame, self.pending = self.pending[:640], self.pending[640:]
            speech = self.is_speech(frame)
            if speech and not self.active:
                self.started = self.cursor - len(self.pre) * 20
                self.active.extend(b"".join(self.pre))
                self.pre.clear()
            if self.active or speech:
                self.active.extend(frame)
                self.silence = 0 if speech else self.silence + 20
                if len(self.active) >= 256000 or self.silence >= 500:
                    windows.append(self.flush())
            else:
                self.pre.append(frame)
            self.cursor += 20
        return windows

    def flush(self):
        if not self.active:
            return None
        data = bytes(self.active)
        self.active.clear()
        self.silence = 0
        return {
            "window_id": str(uuid.uuid4()),
            "start_ms": self.started,
            "end_ms": self.started + len(data) / 32,
            "pcm": data,
        }
