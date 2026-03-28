"""Application constants."""

APP_NAME = "Systemommy"
APP_VERSION = "1.0.0"
ORG_NAME = "Systemommy"

# --- Temperature thresholds (°C) ---
# These are defaults; the app auto-detects safe ranges per hardware.
CPU_TEMP_WARNING = 85
CPU_TEMP_CRITICAL = 92
GPU_TEMP_WARNING = 83
GPU_TEMP_CRITICAL = 90

# --- Overlay defaults ---
OVERLAY_OPACITY = 0.85
OVERLAY_FONT_SIZE = 12
OVERLAY_UPDATE_INTERVAL_MS = 1500
OVERLAY_POSITION_X = 10
OVERLAY_POSITION_Y = 10

# --- Theme colours ---
COLOR_GREEN = "#39ff14"
COLOR_RED = "#ff2d2d"
COLOR_GOLD = "#ffd700"
COLOR_PURPLE = "#b000ff"
COLOR_BG_DARK = "#0a0a0a"
COLOR_BG_PANEL = "#141414"
COLOR_BG_WIDGET = "#1c1c1c"
COLOR_BORDER = "#2a2a2a"
COLOR_TEXT = "#d0d0d0"
COLOR_TEXT_DIM = "#666666"

# --- Thermal correction ---
THERMAL_CORRECTION_COOLDOWN_S = 30
ALERT_SOUND_MAX_PLAYS = 2
ALERT_COOLDOWN_S = 60
