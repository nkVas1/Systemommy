@echo off
title Systemommy
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo [*] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

pip show PySide6 >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing dependencies (this may take a few minutes)...
    pip install --timeout 120 --retries 5 -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        echo If you have a slow connection, try running manually:
        echo   pip install --timeout 300 -r requirements.txt
        pause
        exit /b 1
    )
)

echo [*] Starting Systemommy...
pythonw -m systemommy
if %errorlevel% neq 0 (
    python -m systemommy
)
