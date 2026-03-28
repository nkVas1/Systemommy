"""Central hardware monitor — polls CPU/GPU and emits Qt signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from systemommy.hardware.cpu import CpuReading, read_cpu
from systemommy.hardware.gpu import GpuReading, read_gpu

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwareSnapshot:
    """Combined hardware reading."""

    cpu: CpuReading
    gpu: GpuReading


class HardwareMonitor(QObject):
    """Periodically polls hardware sensors and emits ``reading_updated``."""

    reading_updated = Signal(object)  # HardwareSnapshot

    def __init__(self, interval_ms: int = 1500, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)
        self._latest: HardwareSnapshot | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin polling."""
        self._poll()  # immediate first read
        self._timer.start()

    def stop(self) -> None:
        """Stop polling."""
        self._timer.stop()

    def set_interval(self, ms: int) -> None:
        """Change the polling interval."""
        self._timer.setInterval(ms)

    @property
    def latest(self) -> HardwareSnapshot | None:
        return self._latest

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        try:
            cpu = read_cpu()
            gpu = read_gpu()
            self._latest = HardwareSnapshot(cpu=cpu, gpu=gpu)
            self.reading_updated.emit(self._latest)
        except Exception:
            logger.exception("Hardware polling error.")
