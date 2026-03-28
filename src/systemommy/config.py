"""Configuration persistence via JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from systemommy.constants import (
    ALERT_COOLDOWN_S,
    CPU_TEMP_CRITICAL,
    CPU_TEMP_WARNING,
    GPU_TEMP_CRITICAL,
    GPU_TEMP_WARNING,
    OVERLAY_FONT_SIZE,
    OVERLAY_OPACITY,
    OVERLAY_POSITION_X,
    OVERLAY_POSITION_Y,
    OVERLAY_UPDATE_INTERVAL_MS,
    THRESHOLD_MINIMUM_GAP,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_DIR = Path.home() / ".systemommy"
_CONFIG_FILENAME = "config.json"


@dataclass
class OverlaySettings:
    """Overlay display settings."""

    enabled: bool = True
    opacity: float = OVERLAY_OPACITY
    font_size: int = OVERLAY_FONT_SIZE
    update_interval_ms: int = OVERLAY_UPDATE_INTERVAL_MS
    position_x: int = OVERLAY_POSITION_X
    position_y: int = OVERLAY_POSITION_Y
    show_cpu: bool = True
    show_gpu: bool = True


@dataclass
class AlertSettings:
    """Temperature alert settings."""

    enabled: bool = True
    sound_enabled: bool = True
    cpu_warning: int = CPU_TEMP_WARNING
    cpu_critical: int = CPU_TEMP_CRITICAL
    gpu_warning: int = GPU_TEMP_WARNING
    gpu_critical: int = GPU_TEMP_CRITICAL
    cooldown_s: int = ALERT_COOLDOWN_S

    def __post_init__(self) -> None:
        """Ensure warning thresholds are always below critical thresholds."""
        if self.cpu_warning >= self.cpu_critical:
            self.cpu_warning = self.cpu_critical - THRESHOLD_MINIMUM_GAP
        if self.gpu_warning >= self.gpu_critical:
            self.gpu_warning = self.gpu_critical - THRESHOLD_MINIMUM_GAP


@dataclass
class ThermalSettings:
    """Thermal correction settings."""

    auto_correct_enabled: bool = False
    ask_before_correct: bool = True


@dataclass
class AppConfig:
    """Root application configuration."""

    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    alerts: AlertSettings = field(default_factory=AlertSettings)
    thermal: ThermalSettings = field(default_factory=ThermalSettings)
    start_minimized: bool = False
    start_with_windows: bool = False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def config_path(cls, config_dir: Path | None = None) -> Path:
        """Return the full path to the config file."""
        directory = config_dir or _DEFAULT_CONFIG_DIR
        return directory / _CONFIG_FILENAME

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "AppConfig":
        """Load configuration from disk, returning defaults on any error."""
        path = cls.config_path(config_dir)
        if not path.exists():
            logger.info("No config found at %s — using defaults.", path)
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                overlay=OverlaySettings(**raw.get("overlay", {})),
                alerts=AlertSettings(**raw.get("alerts", {})),
                thermal=ThermalSettings(**raw.get("thermal", {})),
                start_minimized=raw.get("start_minimized", False),
                start_with_windows=raw.get("start_with_windows", False),
            )
        except Exception:
            logger.exception("Failed to load config from %s — using defaults.", path)
            return cls()

    def save(self, config_dir: Path | None = None) -> None:
        """Persist current configuration to disk."""
        path = self.config_path(config_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Configuration saved to %s", path)
