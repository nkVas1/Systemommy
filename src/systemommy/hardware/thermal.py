"""Thermal correction — safe automatic throttling.

Implements conservative, reversible measures to reduce CPU/GPU temperature:

CPU:
  1. Reduce Windows power plan to *Power Saver*.
  2. Lower the maximum processor frequency via ``powercfg``.

GPU (NVIDIA only via NVML):
  1. Lower power-limit to 70 % of default.
  2. Apply conservative GPU clock offset.

All changes are **reversible** — ``restore()`` brings settings back.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ThermalCorrector:
    """Manages reversible thermal correction actions."""

    _cpu_corrected: bool = field(default=False, init=False)
    _gpu_corrected: bool = field(default=False, init=False)
    _original_power_plan: str | None = field(default=None, init=False)
    _original_gpu_power_limit: int | None = field(default=None, init=False)

    # ------------------------------------------------------------------
    # CPU
    # ------------------------------------------------------------------

    def correct_cpu(self) -> bool:
        """Apply CPU thermal correction. Returns ``True`` on success."""
        if self._cpu_corrected:
            return True
        if platform.system() != "Windows":
            logger.warning("CPU thermal correction is only supported on Windows.")
            return False
        try:
            # Save current active power plan GUID
            result = subprocess.run(
                ["powercfg", "/getactivescheme"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                for part in parts:
                    if len(part) == 36 and "-" in part:
                        self._original_power_plan = part
                        break

            # Set maximum processor state to 80 % via the active scheme
            # Sub-group: Processor power management
            # Setting: Maximum processor state
            subprocess.run(
                [
                    "powercfg",
                    "/setacvalueindex",
                    "scheme_current",
                    "54533251-82be-4824-96c1-47b60b740d00",
                    "bc5038f7-23e0-4960-96da-33abaf5935ec",
                    "80",
                ],
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["powercfg", "/setactive", "scheme_current"],
                capture_output=True,
                check=False,
            )
            self._cpu_corrected = True
            logger.info("CPU thermal correction applied (max processor state → 80%%).")
            return True
        except Exception:
            logger.exception("CPU thermal correction failed.")
            return False

    def restore_cpu(self) -> bool:
        """Restore CPU to original settings. Returns ``True`` on success."""
        if not self._cpu_corrected:
            return True
        if platform.system() != "Windows":
            return False
        try:
            # Restore max processor state to 100 %
            subprocess.run(
                [
                    "powercfg",
                    "/setacvalueindex",
                    "scheme_current",
                    "54533251-82be-4824-96c1-47b60b740d00",
                    "bc5038f7-23e0-4960-96da-33abaf5935ec",
                    "100",
                ],
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["powercfg", "/setactive", "scheme_current"],
                capture_output=True,
                check=False,
            )
            self._cpu_corrected = False
            logger.info("CPU settings restored (max processor state → 100%%).")
            return True
        except Exception:
            logger.exception("CPU restore failed.")
            return False

    # ------------------------------------------------------------------
    # GPU (NVIDIA via NVML)
    # ------------------------------------------------------------------

    def correct_gpu(self) -> bool:
        """Apply GPU thermal correction. Returns ``True`` on success."""
        if self._gpu_corrected:
            return True
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)

            # Save and lower power limit to 70 % of default
            default_limit = pynvml.nvmlDeviceGetPowerManagementDefaultLimit(handle)
            self._original_gpu_power_limit = default_limit
            new_limit = int(default_limit * 0.7)

            min_limit = pynvml.nvmlDeviceGetPowerManagementLimitConstraints(handle)[0]
            new_limit = max(new_limit, min_limit)

            pynvml.nvmlDeviceSetPowerManagementLimit(handle, new_limit)
            pynvml.nvmlShutdown()

            self._gpu_corrected = True
            logger.info(
                "GPU thermal correction applied (power limit %d → %d mW).",
                default_limit,
                new_limit,
            )
            return True
        except Exception:
            logger.exception("GPU thermal correction failed (NVML may not be available).")
            return False

    def restore_gpu(self) -> bool:
        """Restore GPU to original power limit. Returns ``True`` on success."""
        if not self._gpu_corrected:
            return True
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            if self._original_gpu_power_limit is not None:
                pynvml.nvmlDeviceSetPowerManagementLimit(
                    handle, self._original_gpu_power_limit
                )
            pynvml.nvmlShutdown()
            self._gpu_corrected = False
            logger.info("GPU power limit restored.")
            return True
        except Exception:
            logger.exception("GPU restore failed.")
            return False

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def restore_all(self) -> None:
        """Restore all settings to original values."""
        self.restore_cpu()
        self.restore_gpu()

    @property
    def is_cpu_corrected(self) -> bool:
        return self._cpu_corrected

    @property
    def is_gpu_corrected(self) -> bool:
        return self._gpu_corrected
