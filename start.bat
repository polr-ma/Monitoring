@echo off
title Live Monitor

echo.
echo ========================================
echo    Starting Live Monitor...
echo ========================================
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found
    echo Please run setup.bat first
    pause
    exit /b 1
)

echo [1/2] Activating venv...
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate venv
    pause
    exit /b 1
)
echo [OK] Venv activated

echo.
echo [2/2] Starting main program...
echo Note: First run will download ~400MB model
echo Press Ctrl+C to stop
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Program exited with code %errorlevel%
) else (
    echo.
    echo [OK] Program exited normally
)

pause