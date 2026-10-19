@echo off
rem Ce raccourci lance le serveur unique et authentifie (31880).
rem Il lance maintenant MissionControl.py, le serveur protege, sur 31880.
cd /d "%~dp0"
start "DIOPTRE Mission Control" /min python "%~dp0MissionControl.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:31880/"
