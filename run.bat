@echo off
chcp 65001 >nul 2>nul
title Systemommy
cd /d "%~dp0"

echo ============================================
echo        Systemommy — Hardware Monitor
echo ============================================
echo.

REM --- Robust pip settings for unstable connections ---
REM PIP_DEFAULT_TIMEOUT affects ALL pip operations, including
REM internal subprocesses that install build dependencies.
set PIP_DEFAULT_TIMEOUT=300
set PIP_RETRIES=4
set PIP_DISABLE_PIP_VERSION_CHECK=1

REM --- PYTHONPATH lets Python find the package in src/ ---
set PYTHONPATH=%~dp0src

REM ---- Check Python ----
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    goto :fail
)

REM ---- Check Python version ----
python -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10 or newer is required.
    echo Current version:
    python --version
    goto :fail
)

REM ---- Create virtual environment ----
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        goto :fail
    )
    echo       Done.
    echo.
)

REM ---- Activate virtual environment ----
call venv\Scripts\activate.bat

REM ---- Install dependencies if needed ----
python -c "import PySide6; import psutil" 2>nul
if %errorlevel% neq 0 (
    echo [2/3] Installing dependencies...
    echo       PySide6 is ~570 MB — this may take several minutes.
    echo       Please wait...
    echo.
    set HAS_LOCAL_WHEELS=0
    dir /b ".wheels\PySide6*.whl" >nul 2>nul && dir /b ".wheels\psutil*.whl" >nul 2>nul && set HAS_LOCAL_WHEELS=1
    if "%HAS_LOCAL_WHEELS%"=="1" (
        echo       Found local wheel cache: .wheels
        echo       Installing offline from local files...
        pip install --no-index --find-links=.wheels -r requirements.txt
    ) else (
        pip install --prefer-binary -r requirements.txt
    )
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Failed to install dependencies.
        echo.
        echo Possible causes:
        echo   - Slow or unstable internet connection
        echo   - PyPI server temporarily unavailable
        echo.
        echo Fast recovery (download once, then install offline):
        echo   1. Open Command Prompt in this folder
        echo   2. venv\Scripts\activate.bat
        echo   3. pip download --dest .wheels -r requirements.txt
        echo   4. Run this script again
        goto :fail
    )
    echo.
    echo       Dependencies installed successfully.
    echo.
)

REM ---- Verify module can be loaded ----
python -c "from systemommy import __version__" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Cannot load Systemommy module.
    echo Please ensure the src\systemommy\ folder is intact.
    goto :fail
)

REM ---- Launch ----
echo [3/3] Starting Systemommy...
start "" pythonw -m systemommy
if %errorlevel% neq 0 (
    echo [!] Launching with console for diagnostics...
    python -m systemommy
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Systemommy exited with an error.
        goto :fail
    )
)
exit /b 0

:fail
echo.
echo ============================================
echo Press any key to exit...
pause >nul
exit /b 1
