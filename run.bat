@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
title Systemommy — Hardware Monitor
cd /d "%~dp0"

REM ============================================================
REM  Systemommy — one-click launcher for Windows
REM
REM  Installs dependencies via requirements.txt (fast, no build
REM  isolation) and runs the app with PYTHONPATH pointing to src/.
REM
REM  Usage:
REM    run.bat                  Normal launch
REM    run.bat --force          Delete venv and reinstall everything
REM    run.bat --console        Launch with a console window (debug)
REM    run.bat --help           Show help
REM ============================================================

REM ---- Parse command-line flags ----
set "FLAG_FORCE=0"
set "FLAG_CONSOLE=0"
for %%A in (%*) do (
    if /i "%%A"=="--force"   set "FLAG_FORCE=1"
    if /i "%%A"=="--console" set "FLAG_CONSOLE=1"
    if /i "%%A"=="--help"    goto :show_help
)

echo.
echo  ============================================
echo        Systemommy  —  Hardware Monitor
echo  ============================================
echo.

REM ========================================================
REM  STEP 1 — Locate a working Python 3.10+ interpreter
REM ========================================================
echo  [1/4] Checking Python...

set "PYTHON="

REM 1a. Windows Python Launcher ("py -3") — most reliable
where py >nul 2>nul
if !errorlevel! equ 0 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
    if !errorlevel! equ 0 (
        set "PYTHON=py -3"
        goto :python_ok
    )
)

REM 1b. Plain "python" on PATH (skip Microsoft Store stub)
where python >nul 2>nul
if !errorlevel! equ 0 (
    python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
    if !errorlevel! equ 0 (
        set "PYTHON=python"
        goto :python_ok
    )
)

REM 1c. "python3" alias (rare on Windows, common on WSL/MSYS2)
where python3 >nul 2>nul
if !errorlevel! equ 0 (
    python3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
    if !errorlevel! equ 0 (
        set "PYTHON=python3"
        goto :python_ok
    )
)

echo        [ERROR] Python 3.10+ is not installed or not in PATH.
echo.
echo        Download Python from: https://www.python.org/downloads/
echo        During installation check "Add Python to PATH".
goto :fail

:python_ok
for /f "delims=" %%v in ('!PYTHON! --version 2^>^&1') do echo        %%v
echo.

REM ========================================================
REM  STEP 2 — Prepare virtual environment
REM ========================================================
set "VENV_DIR=%~dp0venv"
set "VENV_PYTHON=!VENV_DIR!\Scripts\python.exe"
set "VENV_PYTHONW=!VENV_DIR!\Scripts\pythonw.exe"
set "VENV_PIP=!VENV_DIR!\Scripts\pip.exe"
set "VENV_ACTIVATE=!VENV_DIR!\Scripts\activate.bat"

REM 2a. --force: wipe existing venv
if "!FLAG_FORCE!"=="1" (
    if exist "!VENV_DIR!" (
        echo  [2/4] Force mode: removing old environment...
        rmdir /s /q "!VENV_DIR!" 2>nul
        echo        Done.
        echo.
    )
)

REM 2b. Health-check: if venv python is broken, wipe and recreate
if exist "!VENV_PYTHON!" (
    "!VENV_PYTHON!" -c "import sys" >nul 2>nul
    if !errorlevel! neq 0 (
        echo  [!] Virtual environment corrupted — recreating...
        rmdir /s /q "!VENV_DIR!" 2>nul
    )
)

REM 2c. Create venv if it does not exist
if not exist "!VENV_ACTIVATE!" (
    echo  [2/4] Creating virtual environment...
    !PYTHON! -m venv "!VENV_DIR!"
    if !errorlevel! neq 0 (
        echo        [ERROR] Failed to create virtual environment.
        echo.
        echo        Possible causes:
        echo          - Antivirus blocking file creation
        echo          - Insufficient disk space
        echo          - Python was installed without venv support
        goto :fail
    )
    echo        Done.
    echo.
) else (
    echo  [2/4] Virtual environment OK.
    echo.
)

REM 2d. Activate
call "!VENV_ACTIVATE!"

REM ========================================================
REM  STEP 3 — Install / verify packages
REM
REM  Uses requirements.txt for a direct pip install.
REM  No build isolation, no setuptools download — just binary
REM  wheels from PyPI. This is significantly faster and more
REM  reliable than "pip install -e ." which needed to download
REM  setuptools>=68.0 into an isolated build environment.
REM ========================================================
set "PYTHONPATH=%~dp0src"
set "NEEDS_INSTALL=0"

if "!FLAG_FORCE!"=="1" (
    set "NEEDS_INSTALL=1"
)

REM Quick check: are runtime deps importable? (keep in sync with requirements.txt)
if "!NEEDS_INSTALL!"=="0" (
    python -c "import PySide6; import psutil" >nul 2>nul
    if !errorlevel! neq 0 set "NEEDS_INSTALL=1"
)

if "!NEEDS_INSTALL!"=="1" (
    echo  [3/4] Installing dependencies...
    echo        PySide6 is ~570 MB — first install may take a few minutes.
    echo.

    REM Upgrade pip itself (don't fail if offline — old pip may be OK)
    echo        Upgrading pip...
    python -m pip install --upgrade pip --quiet --timeout 30 2>nul
    if !errorlevel! neq 0 (
        echo        [note] pip upgrade skipped — continuing with current version.
    ) else (
        echo        Done.
    )
    echo.

    REM Pip settings: generous timeout, retries, no version nag
    set "PIP_DEFAULT_TIMEOUT=300"
    set "PIP_RETRIES=5"
    set "PIP_DISABLE_PIP_VERSION_CHECK=1"

    REM Check for local wheel cache (.wheels directory)
    set "USE_CACHE=0"
    if exist ".wheels\" (
        set "_HAS_QT=0"
        set "_HAS_PS=0"
        dir /b ".wheels\PySide6*.whl" >nul 2>nul && set "_HAS_QT=1"
        dir /b ".wheels\psutil*.whl"  >nul 2>nul && set "_HAS_PS=1"
        if "!_HAS_QT!"=="1" if "!_HAS_PS!"=="1" set "USE_CACHE=1"
    )

    if "!USE_CACHE!"=="1" (
        echo        Installing from local cache: .wheels\
        pip install --no-index --find-links=.wheels -r requirements.txt
    ) else (
        echo        Downloading from PyPI...
        pip install --prefer-binary -r requirements.txt
    )

    if !errorlevel! neq 0 (
        echo.
        echo        [ERROR] Installation failed.
        echo.
        echo        Possible causes:
        echo          - Unstable internet connection
        echo          - PyPI temporarily unavailable
        echo          - Insufficient disk space (PySide6 needs ~1.5 GB)
        echo.
        echo        Recovery options:
        echo          1. Run this script again
        echo          2. run.bat --force   (full reinstall)
        echo          3. Pre-download packages for offline install:
        echo               venv\Scripts\activate.bat
        echo               pip download --dest .wheels PySide6 psutil
        echo               run.bat
        goto :fail
    )

    echo.
    echo        Installation complete.
    echo.
) else (
    echo  [3/4] All packages are up to date.
    echo.
)

REM ========================================================
REM  STEP 4 — Launch the application
REM ========================================================
python -c "from systemommy import __version__ as v; print(f'        Systemommy v{v}')" 2>nul
if !errorlevel! neq 0 (
    echo        [ERROR] Cannot find systemommy module.
    echo        Try:  run.bat --force
    goto :fail
)

echo  [4/4] Launching Systemommy...
echo.

if "!FLAG_CONSOLE!"=="1" (
    echo        Console mode — press Ctrl+C to stop.
    echo.
    python -m systemommy
    goto :eof
)

REM Launch windowless via pythonw (no console window).
start "" "!VENV_PYTHONW!" -m systemommy

echo        Systemommy is running.
echo        Look for the green "S" icon in your system tray.
echo.
timeout /t 3 /nobreak >nul
exit /b 0

REM ============================================================
:show_help
echo.
echo   Systemommy — Hardware Temperature Monitor
echo.
echo   Usage:  run.bat [options]
echo.
echo   Options:
echo     --force     Delete virtual environment and reinstall everything
echo     --console   Launch with a visible console window (diagnostics)
echo     --help      Show this message
echo.
echo   Offline install (for slow or no internet):
echo     1. On a machine with internet, run:
echo          python -m venv venv
echo          venv\Scripts\activate.bat
echo          pip download --dest .wheels PySide6 psutil
echo     2. Copy the .wheels folder into this directory.
echo     3. run.bat
echo.
exit /b 0

REM ============================================================
:fail
echo.
echo  ============================================
echo   Tips:
echo     run.bat --force     full reinstall
echo     run.bat --console   see error details
echo     run.bat --help      all options
echo  ============================================
echo.
echo  Press any key to exit...
pause >nul
exit /b 1
