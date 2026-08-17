@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title Ticket Monitor

echo ============================================
echo   SHC Student Ticket Monitor
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python ready
echo.

pip install -r requirements.txt -q 2>nul
echo [OK] Dependencies ready
echo.

echo [START] Monitoring... Press Ctrl+C to stop
echo.

python monitor.py

pause