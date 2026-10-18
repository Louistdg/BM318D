"""BM318d — lanceur unique, sans fenêtre de terminal.

Démarre Mission Control si nécessaire, attend qu'il réponde, puis ouvre la page
dans le navigateur par défaut. Un second lancement n'ouvre pas un second serveur.
"""
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

RACINE = Path(__file__).resolve().parent
PORT = int(os.environ.get('MC_PORT') or 31880)
URL = 'http://127.0.0.1:%d/' % PORT
LOGS = RACINE / 'logs'
LOGS.mkdir(exist_ok=True)


def repond():
    try:
        with urllib.request.urlopen(URL, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    if repond():
        webbrowser.open(URL)
        return 0
    journal = open(LOGS / 'mission-control.log', 'a', encoding='utf-8')
    creation = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    serveur = subprocess.Popen([sys.executable, str(RACINE / 'MissionControl.py')],
                               cwd=str(RACINE), stdout=journal, stderr=journal,
                               creationflags=creation)
    (LOGS / 'mission-control.pid').write_text(str(serveur.pid), encoding='utf-8')
    for _ in range(120):
        if repond():
            webbrowser.open(URL)
            return 0
        if serveur.poll() is not None:
            return 1
        time.sleep(0.5)
    return 1


if __name__ == '__main__':
    sys.exit(main())
