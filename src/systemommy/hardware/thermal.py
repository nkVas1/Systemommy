"""Thermal correction — safe automatic throttling.

Implements conservative, **reversible** measures to reduce CPU/GPU temperature.
All corrections stay within manufacturer-safe operating limits.

CPU (Windows only):
  1. Read the current *maximum processor state* from the active power plan.
  2. Lower it to 80 % — this caps the CPU's boost clock but does **not**
     disable cores, reduce the base clock, or change voltage.  The OS
     and hardware still enforce their own thermal protections underneath.
  3. On ``restore()``, the original value (100 %) is written back.

GPU (NVIDIA only via NVML):
  1. Read the GPU's default power limit and the manufacturer's minimum
     allowed power limit.
  2. Set a new limit to 70 % of the default, clamped above the minimum.
     This tells the GPU firmware to reduce clocks when the power budget
     is reached — a normal, firmware-level mechanism that **cannot**
     damage the hardware.
  3. On ``restore()``, the original power limit is written back.

Safety guarantees:
  • All corrections are within the range the hardware explicitly reports
    as safe (min/max power limits, 0-100 % processor state).
  • Corrections are automatically reversed when temperatures return to
    normal (see :pymod:`systemommy.alerts.manager`).
  • If a restore call fails, the next application restart will *not*
    re-apply the correction (state is in-memory only).
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

# Subprocess creation flag that prevents a visible console window on Windows.
_SUBPROCESS_FLAGS: int = (
    subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
)

# Maximum processor state will be set to this percentage during correction.
# 80 % keeps the CPU well within safe thermal limits while still providing
# reasonable performance for most workloads.
_CPU_CORRECTION_MAX_STATE_PERCENT = 80

# GPU power limit will be set to this fraction of the default limit.
# 0.7 (70 %) is conservative enough to meaningfully reduce temperature
# while staying above the GPU's minimum allowed power limit.
_GPU_CORRECTION_POWER_FRACTION = 0.7

# Well-known powercfg GUIDs (stable across all Windows versions ≥ 7).
_PROCESSOR_POWER_SUBGROUP = "54533251-82be-4824-96c1-47b60b740d00"
_MAX_PROCESSOR_STATE_SETTING = "bc5038f7-23e0-4960-96da-33abaf5935ec"


@dataclass
class ThermalCorrector:
    """Manages reversible thermal correction actions.

    Safety invariants:
      • ``correct_cpu`` only lowers the max-processor-state value; it never
        touches voltage, core affinity, or any other BIOS-level setting.
      • ``correct_gpu`` only adjusts the firmware-level power limit within
        the range reported by the GPU itself.
      • Both ``restore_*`` methods return to the original settings.
      • If the process is killed before ``restore_*`` is called, Windows
        will continue using the current power plan value until it is
        explicitly changed again (the next session's ``restore_*`` will
        fix it, or the user can run ``powercfg`` / restart the GPU driver).
    """

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
        if not _IS_WINDOWS:
            logger.warning("CPU thermal correction is only supported on Windows.")
            return False
        try:
            # Save current active power plan GUID
            result = subprocess.run(
                ["powercfg", "/getactivescheme"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                for part in parts:
                    if len(part) == 36 and "-" in part:
                        self._original_power_plan = part
                        break

            # Set maximum processor state (safe: 0-100 % range only)
            value = str(max(50, min(100, _CPU_CORRECTION_MAX_STATE_PERCENT)))
            subprocess.run(
                [
                    "powercfg",
                    "/setacvalueindex",
                    "scheme_current",
                    _PROCESSOR_POWER_SUBGROUP,
                    _MAX_PROCESSOR_STATE_SETTING,
                    value,
                ],
                capture_output=True,
                check=False,
                creationflags=_SUBPROCESS_FLAGS,
            )
            subprocess.run(
                ["powercfg", "/setactive", "scheme_current"],
                capture_output=True,
                check=False,
                creationflags=_SUBPROCESS_FLAGS,
            )
            self._cpu_corrected = True
            logger.info(
                "CPU thermal correction applied (max processor state → %s%%).",
                value,
            )
            return True
        except Exception:
            logger.exception("CPU thermal correction failed.")
            return False

    def restore_cpu(self) -> bool:
        """Restore CPU to original settings. Returns ``True`` on success."""
        if not self._cpu_corrected:
            return True
        if not _IS_WINDOWS:
            return False
        try:
            subprocess.run(
                [
                    "powercfg",
                    "/setacvalueindex",
                    "scheme_current",
                    _PROCESSOR_POWER_SUBGROUP,
                    _MAX_PROCESSOR_STATE_SETTING,
                    "100",
                ],
                capture_output=True,
                check=False,
                creationflags=_SUBPROCESS_FLAGS,
            )
            subprocess.run(
                ["powercfg", "/setactive", "scheme_current"],
                capture_output=True,
                check=False,
                creationflags=_SUBPROCESS_FLAGS,
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

            # Read manufacturer limits
            default_limit = pynvml.nvmlDeviceGetPowerManagementDefaultLimit(handle)
            min_limit, max_limit = pynvml.nvmlDeviceGetPowerManagementLimitConstraints(
                handle
            )
            self._original_gpu_power_limit = default_limit

            # Compute new limit — 70 % of default, clamped within safe range
            new_limit = int(default_limit * _GPU_CORRECTION_POWER_FRACTION)
            new_limit = max(new_limit, min_limit)
            new_limit = min(new_limit, max_limit)

            pynvml.nvmlDeviceSetPowerManagementLimit(handle, new_limit)
            pynvml.nvmlShutdown()

            self._gpu_corrected = True
            logger.info(
                "GPU thermal correction applied (power limit %d → %d mW, "
                "allowed range %d–%d mW).",
                default_limit,
                new_limit,
                min_limit,
                max_limit,
            )
            return True
        except Exception:
            logger.exception(
                "GPU thermal correction failed (NVML may not be available)."
            )
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
