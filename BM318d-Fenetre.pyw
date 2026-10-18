"""BM318d — petite fenêtre de contrôle, sans terminal.

Elle ne remplace pas la page web : elle sert à voir si le service tourne, à
l'ouvrir, à le sauvegarder et à l'arrêter proprement. Toute la logique passe par
l'API déjà protégée par jeton ; la fenêtre ne connaît aucun secret.
"""
import json
import os
import re
import subprocess
import sys
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent
PORT = int(os.environ.get('MC_PORT') or 31880)
URL = 'http://127.0.0.1:%d/' % PORT
LOGS = RACINE / 'logs'


def _ouvrir(chemin):
    with urllib.request.urlopen(chemin, timeout=4) as r:
        return r.read().decode('utf-8', 'replace')


def jeton():
    page = _ouvrir(URL)
    trouve = re.search(r'name="mc-token" content="([^"]+)"', page)
    return trouve.group(1) if trouve else None


def appel(chemin, corps=None):
    j = jeton()
    if not j:
        raise RuntimeError('Jeton introuvable')
    donnees = json.dumps(corps or {}).encode()
    requete = urllib.request.Request(URL + chemin, data=donnees, method='POST',
                                     headers={'Content-Type': 'application/json', 'X-MC-Token': j})
    with urllib.request.urlopen(requete, timeout=8) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def en_ligne():
    try:
        _ouvrir(URL)
        return True
    except Exception:
        return False


def demarrer():
    LOGS.mkdir(exist_ok=True)
    journal = open(LOGS / 'mission-control.log', 'a', encoding='utf-8')
    creation = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    return subprocess.Popen([sys.executable, str(RACINE / 'MissionControl.py')],
                            cwd=str(RACINE), stdout=journal, stderr=journal,
                            creationflags=creation)


class Fenetre:
    def __init__(self, racine):
        self.racine = racine
        self.age = 0
        racine.title('BM318d Control Center')
        racine.geometry('360x190')
        racine.resizable(False, False)
        self.statut = tk.Label(racine, text='...', font=('Segoe UI', 11))
        self.statut.pack(pady=(18, 6))
        self.detail = tk.Label(racine, text='', fg='#555')
        self.detail.pack()
        boutons = tk.Frame(racine)
        boutons.pack(pady=16)
        tk.Button(boutons, text='Ouvrir', width=10, command=self.ouvrir).grid(row=0, column=0, padx=4)
        tk.Button(boutons, text='Sauvegarder', width=12, command=self.sauvegarder).grid(row=0, column=1, padx=4)
        tk.Button(boutons, text='Arrêter', width=10, command=self.arreter).grid(row=0, column=2, padx=4)
        self.rafraichir()

    def ouvrir(self):
        import webbrowser
        webbrowser.open(URL)

    def sauvegarder(self):
        try:
            r = appel('api/mc/backup')
            self.detail.config(text='Sauvegarde : ' + str(r.get('file')))
        except Exception as e:
            self.detail.config(text='Erreur : ' + str(e)[:80])

    def arreter(self):
        try:
            appel('api/mc/shutdown')
            self.statut.config(text='Arrêt demandé')
        except Exception as e:
            self.detail.config(text='Erreur : ' + str(e)[:80])
        self.racine.after(800, self.racine.destroy)

    def rafraichir(self):
        if en_ligne():
            self.statut.config(text='● En ligne', fg='#1f7a4d')
            try:
                n = appel('api/mc/history')
                self.detail.config(text='%d entrées de journal' % len(n.get('audit', [])))
            except Exception:
                self.detail.config(text='')
        else:
            self.statut.config(text='○ Hors ligne', fg='#a33')
            self.detail.config(text='Le service démarrera au prochain lancement')
        self.racine.after(3000, self.rafraichir)


def main():
    racine = tk.Tk()
    Fenetre(racine)
    racine.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
