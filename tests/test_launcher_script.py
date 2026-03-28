"""Tests for Windows launcher reliability safeguards."""

from __future__ import annotations

from pathlib import Path


def _run_bat_text() -> str:
    return (Path(__file__).resolve().parents[1] / "run.bat").read_text(
        encoding="utf-8"
    )


def test_launcher_supports_offline_wheel_cache() -> None:
    """Launcher must detect .wheels/ and install from it when available."""
    content = _run_bat_text()
    assert ".wheels" in content
    assert "PySide6*.whl" in content
    assert "psutil*.whl" in content
    assert "--no-index" in content
    assert "--find-links" in content


def test_launcher_upgrades_pip_before_install() -> None:
    """Pip must be upgraded to avoid PEP 660 / wheel compatibility issues."""
    content = _run_bat_text()
    assert "pip install --upgrade pip" in content


def test_launcher_uses_requirements_txt() -> None:
    """Package dependencies must be installed via pip install -r requirements.txt."""
    content = _run_bat_text()
    assert "pip install" in content
    assert "requirements.txt" in content


def test_launcher_supports_force_flag() -> None:
    """--force flag must be available for full reinstall."""
    content = _run_bat_text()
    assert "--force" in content


def test_launcher_supports_console_flag() -> None:
    """--console flag must be available for diagnostic launch."""
    content = _run_bat_text()
    assert "--console" in content


def test_launcher_checks_python_version() -> None:
    """Launcher must verify Python >= 3.10."""
    content = _run_bat_text()
    assert "3,10" in content or "3, 10" in content


def test_launcher_sets_pythonpath() -> None:
    """Launcher must set PYTHONPATH to src/ for package resolution."""
    content = _run_bat_text()
    assert "PYTHONPATH" in content
    assert "src" in content


def test_launcher_detects_broken_venv() -> None:
    """Launcher must detect and recreate corrupted virtual environments."""
    content = _run_bat_text()
    assert "corrupted" in content.lower() or "broken" in content.lower()
