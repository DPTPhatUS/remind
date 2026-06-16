class FrameSampler:
    def __init__(self, *, sample_interval_ms: int) -> None:
        self.sample_interval_ms = sample_interval_ms
        self._last_processed_at_ms: int | None = None

    def should_process(self, captured_at_ms: int) -> bool:
        if self._last_processed_at_ms is None:
            self._last_processed_at_ms = captured_at_ms
            return True
        if captured_at_ms - self._last_processed_at_ms < self.sample_interval_ms:
            return False
        self._last_processed_at_ms = captured_at_ms
        return True
