@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
echo Testing push notification...
python monitor.py --test-push
pause