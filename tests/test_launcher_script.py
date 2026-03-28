"""Tests for Windows launcher reliability safeguards."""

from __future__ import annotations

from pathlib import Path


def _run_bat_text() -> str:
    return (Path(__file__).resolve().parents[1] / "run.bat").read_text(
        encoding="utf-8"
    )


def test_launcher_uses_local_wheel_cache_when_available() -> None:
    content = _run_bat_text()
    assert 'dir /b ".wheels\\PySide6*.whl" >nul 2>nul' in content
    assert 'dir /b ".wheels\\psutil*.whl" >nul 2>nul' in content
    assert "if %errorlevel% equ 0" in content
    assert "pip install --no-index --find-links=.wheels -r requirements.txt" in content


def test_launcher_does_not_force_pip_upgrade_on_first_run() -> None:
    content = _run_bat_text()
    assert "python -m pip install --upgrade pip" not in content
    assert "pip install --prefer-binary -r requirements.txt" in content
