@echo off
title Live Monitor Setup

echo.
echo ========================================
echo    Live Monitor - Setup
echo ========================================
echo.

echo [1/4] Checking Python ...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    echo Please install Python 3.10 or later
    echo https://www.python.org/downloads/
    echo Check "Add Python to PATH"
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Python version: %PYVER%

echo.
echo [2/4] Creating venv ...
if not exist ".venv" (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create venv
        pause
        exit /b 1
    )
    echo [OK] Venv created
) else (
    echo [OK] Venv exists
)

echo.
echo [3/4] Upgrading pip ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
echo [OK] Pip upgraded

echo.
echo [4/4] Installing dependencies ...
echo This may take 5-10 minutes
echo.
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Installation failed
    echo Please check your network
    pause
    exit /b 1
)

echo.
echo ========================================
echo    [OK] Setup complete
echo.
echo    Run start_monitor.bat
echo ========================================
echo.
echo Note: First run will download models
echo.
pause