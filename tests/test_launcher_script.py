"""Tests for Windows launcher reliability safeguards."""

from __future__ import annotations

from pathlib import Path


def _run_bat_text() -> str:
    return (Path(__file__).resolve().parents[1] / "run.bat").read_text(
        encoding="utf-8"
    )


def test_launcher_uses_local_wheel_cache_when_available() -> None:
    content = _run_bat_text()
    assert "set HAS_LOCAL_WHEELS=0" in content
    assert "set HAS_PYSIDE6_WHEEL=0" in content
    assert "set HAS_PSUTIL_WHEEL=0" in content
    assert ".wheels" in content
    assert "PySide6*.whl" in content
    assert "psutil*.whl" in content
    assert 'if "%HAS_PYSIDE6_WHEEL%"=="1"' in content
    assert 'if "%HAS_PSUTIL_WHEEL%"=="1"' in content
    assert "set HAS_LOCAL_WHEELS=1" in content
    assert 'if "%HAS_LOCAL_WHEELS%"=="1" (' in content
    assert "pip install --no-index --find-links=.wheels -r requirements.txt" in content


def test_launcher_does_not_force_pip_upgrade_on_first_run() -> None:
    content = _run_bat_text()
    assert "python -m pip install --upgrade pip" not in content
    assert "pip install --prefer-binary -r requirements.txt" in content
