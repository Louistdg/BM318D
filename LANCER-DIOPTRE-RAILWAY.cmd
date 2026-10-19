@echo off
rem Ancien raccourci : il lancait DIOPTRE-WebServer.py sur 31879, sans authentification.
rem Il lance maintenant MissionControl.py, le serveur protege, sur 31880.
cd /d "%~dp0"
start "DIOPTRE Mission Control" /min python "%~dp0MissionControl.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:31880/"
