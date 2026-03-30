"""Tests for temperature history storage."""

import time

from systemommy.hardware.history import TemperatureHistory, TemperaturePoint


class TestTemperaturePoint:
    """Ensure TemperaturePoint is immutable and stores values."""

    def test_creation(self) -> None:
        p = TemperaturePoint(timestamp=100.0, cpu_temp=65.0, gpu_temp=72.5)
        assert p.timestamp == 100.0
        assert p.cpu_temp == 65.0
        assert p.gpu_temp == 72.5

    def test_none_temps(self) -> None:
        p = TemperaturePoint(timestamp=100.0, cpu_temp=None, gpu_temp=None)
        assert p.cpu_temp is None
        assert p.gpu_temp is None


class TestTemperatureHistory:
    """Ensure history recording and retrieval work correctly."""

    def test_record_and_length(self) -> None:
        h = TemperatureHistory()
        assert len(h) == 0
        h.record(cpu_temp=55.0, gpu_temp=60.0)
        assert len(h) == 1
        h.record(cpu_temp=56.0, gpu_temp=61.0)
        assert len(h) == 2

    def test_full_session_returns_all(self) -> None:
        h = TemperatureHistory()
        h.record(cpu_temp=50.0, gpu_temp=55.0)
        h.record(cpu_temp=60.0, gpu_temp=65.0)
        points = h.full_session()
        assert len(points) == 2
        assert points[0].cpu_temp == 50.0
        assert points[1].cpu_temp == 60.0

    def test_recent_filters_by_time(self) -> None:
        h = TemperatureHistory()
        # Manually insert old and new points
        old_ts = time.time() - 3600  # 1 hour ago
        h._data.append(TemperaturePoint(timestamp=old_ts, cpu_temp=50.0, gpu_temp=55.0))
        h.record(cpu_temp=70.0, gpu_temp=75.0)  # now

        recent = h.recent(minutes=15.0)
        assert len(recent) == 1
        assert recent[0].cpu_temp == 70.0

        all_pts = h.full_session()
        assert len(all_pts) == 2

    def test_max_points_limit(self) -> None:
        h = TemperatureHistory(max_points=5)
        for i in range(10):
            h.record(cpu_temp=float(i), gpu_temp=float(i))
        assert len(h) == 5
        pts = h.full_session()
        assert pts[0].cpu_temp == 5.0  # oldest retained

    def test_clear_resets(self) -> None:
        h = TemperatureHistory()
        h.record(cpu_temp=55.0, gpu_temp=60.0)
        assert len(h) == 1
        h.clear()
        assert len(h) == 0

    def test_session_start_is_set(self) -> None:
        before = time.time()
        h = TemperatureHistory()
        after = time.time()
        assert before <= h.session_start <= after

    def test_none_temps_recorded(self) -> None:
        h = TemperatureHistory()
        h.record(cpu_temp=None, gpu_temp=None)
        pts = h.full_session()
        assert len(pts) == 1
        assert pts[0].cpu_temp is None
        assert pts[0].gpu_temp is None
