"""Temperature history storage for graphing.

Stores timestamped CPU/GPU temperature readings for the current session.
Provides helpers to retrieve data for "recent" (last N minutes) and
"full session" views.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TemperaturePoint:
    """Single timestamped temperature reading."""

    timestamp: float  # ``time.time()``
    cpu_temp: float | None  # °C or ``None``
    gpu_temp: float | None  # °C or ``None``


class TemperatureHistory:
    """Ring-buffer backed temperature history.

    Stores up to *max_points* entries (default 14 400 — enough for
    6 hours at 1.5 s intervals).

    Parameters
    ----------
    max_points:
        Maximum number of points to keep.  Older entries are discarded.
    """

    def __init__(self, max_points: int = 14_400) -> None:
        self._data: deque[TemperaturePoint] = deque(maxlen=max_points)
        self._session_start: float = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, cpu_temp: float | None, gpu_temp: float | None) -> None:
        """Append a new temperature point with the current timestamp."""
        self._data.append(
            TemperaturePoint(
                timestamp=time.time(),
                cpu_temp=cpu_temp,
                gpu_temp=gpu_temp,
            )
        )

    @property
    def session_start(self) -> float:
        """Timestamp when this history instance was created."""
        return self._session_start

    def recent(self, minutes: float = 15.0) -> list[TemperaturePoint]:
        """Return points from the last *minutes* minutes."""
        cutoff = time.time() - minutes * 60
        return [p for p in self._data if p.timestamp >= cutoff]

    def full_session(self) -> list[TemperaturePoint]:
        """Return all recorded points for the current session."""
        return list(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        """A history instance is always truthy (even when empty).

        Without this override, an empty history evaluates to ``False``
        (because ``__len__`` returns ``0``), which can cause subtle bugs
        when used with ``or`` expressions for default values.
        """
        return True

    def clear(self) -> None:
        """Discard all data and reset session start time."""
        self._data.clear()
        self._session_start = time.time()
