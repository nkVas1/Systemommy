"""Tests for the metrics graph data flow and rendering.

Verifies that the TemperatureHistory → MetricsTab → Graph pipeline works
correctly, including the critical fix where an empty history must still
share the same object identity with the MainWindow.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication

from systemommy.config import AppConfig
from systemommy.hardware.cpu import CpuReading
from systemommy.hardware.gpu import GpuReading
from systemommy.hardware.history import TemperatureHistory, TemperaturePoint
from systemommy.hardware.monitor import HardwareSnapshot
from systemommy.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    """Provide a QApplication instance for the test module."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestHistorySharing:
    """Ensure MainWindow shares the same TemperatureHistory object."""

    def test_empty_history_identity(self, qapp: QApplication) -> None:
        """An empty TemperatureHistory passed to MainWindow must not be
        replaced by a new instance (the 'or' bug).
        """
        history = TemperatureHistory()
        assert len(history) == 0  # empty
        window = MainWindow(AppConfig(), history)
        assert window._history is history
        assert window.metrics_tab._history is history

    def test_nonempty_history_identity(self, qapp: QApplication) -> None:
        history = TemperatureHistory()
        history.record(cpu_temp=50.0, gpu_temp=60.0)
        window = MainWindow(AppConfig(), history)
        assert window._history is history


class TestGraphDataFlow:
    """Ensure temperature data flows from history to the graph widget."""

    def test_graph_receives_data_on_metrics_tab(self, qapp: QApplication) -> None:
        """When the Metrics tab is active, update_reading must populate the
        graph with the current history data.
        """
        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)

        # Record data (simulating hardware monitor polling)
        for i in range(5):
            history.record(cpu_temp=None, gpu_temp=55.0 + i)

        # Switch to Metrics tab
        window.tabs.setCurrentWidget(window.metrics_tab)
        qapp.processEvents()

        # The tab-switch signal should have refreshed the graph
        assert len(window.metrics_tab.graph._points) > 0

    def test_graph_updates_on_reading_while_visible(
        self, qapp: QApplication
    ) -> None:
        """Graph should update when update_reading is called while
        the Metrics tab is current.
        """
        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)
        window.tabs.setCurrentWidget(window.metrics_tab)
        qapp.processEvents()

        # Simulate reading
        history.record(cpu_temp=70.0, gpu_temp=65.0)
        snapshot = HardwareSnapshot(
            cpu=CpuReading(temperature=70.0, usage_percent=30.0),
            gpu=GpuReading(temperature=65.0, usage_percent=20.0, name="Test GPU"),
        )
        window.update_reading(snapshot)
        qapp.processEvents()

        assert len(window.metrics_tab.graph._points) >= 1

    def test_tab_switch_refreshes_graph(self, qapp: QApplication) -> None:
        """Switching from another tab to Metrics should immediately
        refresh the graph with accumulated data.
        """
        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)

        # Start on Dashboard
        window.tabs.setCurrentWidget(window.dashboard_tab)
        qapp.processEvents()

        # Record data while NOT on Metrics tab
        for i in range(10):
            history.record(cpu_temp=45.0 + i, gpu_temp=55.0 + i)

        # Graph should be empty (not refreshed yet)
        assert len(window.metrics_tab.graph._points) == 0

        # Switch to Metrics tab → should auto-refresh
        window.tabs.setCurrentWidget(window.metrics_tab)
        qapp.processEvents()
        # The deferred QTimer.singleShot(0, ...) fires in the next event cycle
        qapp.processEvents()

        assert len(window.metrics_tab.graph._points) == 10


class TestGraphRendering:
    """Verify the graph widget renders correctly."""

    def test_graph_shows_placeholder_when_empty(
        self, qapp: QApplication
    ) -> None:
        """An empty graph should display a 'Waiting for data' message."""
        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)
        window.tabs.setCurrentWidget(window.metrics_tab)
        qapp.processEvents()
        qapp.processEvents()
        # With no data, graph should have 0 points and show placeholder
        assert len(window.metrics_tab.graph._points) == 0

    def test_graph_has_opaque_paint_attribute(
        self, qapp: QApplication
    ) -> None:
        """The graph widget should have WA_OpaquePaintEvent set."""
        from PySide6.QtCore import Qt

        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)
        graph = window.metrics_tab.graph
        assert graph.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def test_metrics_tab_index_stored(self, qapp: QApplication) -> None:
        """MainWindow must store the metrics tab index for robust comparison."""
        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)
        assert hasattr(window, "_metrics_tab_index")
        assert window._metrics_tab_index == window.tabs.indexOf(
            window.metrics_tab,
        )

    def test_update_reading_refreshes_graph_via_index(
        self, qapp: QApplication
    ) -> None:
        """update_reading should refresh graph using index comparison."""
        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)

        # Switch to metrics tab
        window.tabs.setCurrentWidget(window.metrics_tab)
        qapp.processEvents()
        qapp.processEvents()

        # Record data and simulate a hardware reading
        history.record(cpu_temp=60.0, gpu_temp=70.0)
        snapshot = HardwareSnapshot(
            cpu=CpuReading(temperature=60.0, usage_percent=40.0),
            gpu=GpuReading(temperature=70.0, usage_percent=30.0, name="GPU"),
        )
        window.update_reading(snapshot)
        qapp.processEvents()
        qapp.processEvents()

        assert len(window.metrics_tab.graph._points) >= 1

    def test_graph_with_none_cpu_still_shows_gpu(
        self, qapp: QApplication
    ) -> None:
        """When CPU temp is None, the GPU line should still be renderable."""
        history = TemperatureHistory()
        config = AppConfig()
        window = MainWindow(config, history)

        # Record data with None CPU temps (simulating Windows without
        # OHM/LHWM)
        for i in range(5):
            history.record(cpu_temp=None, gpu_temp=60.0 + i)

        window.tabs.setCurrentWidget(window.metrics_tab)
        qapp.processEvents()
        qapp.processEvents()

        graph = window.metrics_tab.graph
        assert len(graph._points) == 5
        # GPU temps should be in the range calculation
        assert graph._max_temp > 60.0
        # At least one GPU temp is present
        gpu_vals = [p.gpu_temp for p in graph._points if p.gpu_temp is not None]
        assert len(gpu_vals) == 5
