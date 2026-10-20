@echo off
cd /d "%~dp0"
start "TREDIO Mission Control" /min python "%~dp0MissionControl.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:31880/"
