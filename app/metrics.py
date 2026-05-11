"""In-memory service metrics for basic operational visibility."""
from threading import Lock


class ServiceMetrics:
    """Thread-safe counters for conversion API."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._values = {
            "conversion_requests_total": 0,
            "conversion_success_total": 0,
            "conversion_failure_total": 0,
            "conversion_rejected_total": 0,
            "conversion_uploaded_bytes_total": 0,
        }

    def increment(self, key: str, value: int = 1) -> None:
        """Increase a metric counter by the given value."""
        with self._lock:
            self._values[key] = self._values.get(key, 0) + value

    def snapshot(self) -> dict[str, int]:
        """Return a copy of current metric values."""
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        """Reset all metric counters to zero."""
        with self._lock:
            for key in self._values:
                self._values[key] = 0


service_metrics = ServiceMetrics()
