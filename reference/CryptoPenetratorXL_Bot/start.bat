@echo off
title CryptoPenetratorXL v2.1
cd /d "%~dp0"

:: Activate virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [ERROR] Virtual environment not found!
    echo Run: python -m venv .venv
    echo Then: .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ===================================
echo  CryptoPenetratorXL  v2.1
echo  Starting trading terminal...
echo ===================================
echo.

python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with errors.
    pause
)
