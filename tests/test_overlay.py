"""Tests for overlay helper functions."""

from systemommy.constants import COLOR_GOLD, COLOR_GREEN, COLOR_RED, COLOR_TEXT_DIM
from systemommy.overlay.widget import _temp_color


class TestTempColor:
    """Verify colour selection based on temperature thresholds."""

    def test_none_returns_dim(self) -> None:
        assert _temp_color(None, 80, 90) == COLOR_TEXT_DIM

    def test_below_warning_returns_green(self) -> None:
        assert _temp_color(60.0, 80, 90) == COLOR_GREEN

    def test_at_warning_returns_gold(self) -> None:
        assert _temp_color(80.0, 80, 90) == COLOR_GOLD

    def test_above_warning_below_critical_returns_gold(self) -> None:
        assert _temp_color(85.0, 80, 90) == COLOR_GOLD

    def test_at_critical_returns_red(self) -> None:
        assert _temp_color(90.0, 80, 90) == COLOR_RED

    def test_above_critical_returns_red(self) -> None:
        assert _temp_color(100.0, 80, 90) == COLOR_RED
