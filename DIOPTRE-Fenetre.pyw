"""TREDIO — petite fenêtre de contrôle, sans terminal.

Elle ne remplace pas la page web : elle sert à voir si le service tourne, à
l'ouvrir, à le sauvegarder et à l'arrêter proprement. L'arrêt et la sauvegarde
n'affichent un succès que si le serveur le confirme. Le jeton administrateur est
lu dans logs/admin-token.txt et n'est ni affiché ni journalisé.
"""
import json
import os
import re
import subprocess
import sys
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


def jeton_admin():
    chemin = LOGS / 'admin-token.txt'
    if not chemin.is_file():
        return None
    valeur = chemin.read_text(encoding='utf-8').strip()
    return valeur or None


def appel(chemin, corps=None, admin=False):
    j = jeton()
    if not j:
        raise RuntimeError('Jeton de session introuvable')
    entetes = {'Content-Type': 'application/json', 'X-MC-Token': j}
    if admin:
        a = jeton_admin()
        if not a:
            raise RuntimeError('Jeton administrateur absent')
        entetes['X-MC-Admin'] = a
    donnees = json.dumps(corps or {}).encode()
    requete = urllib.request.Request(URL + chemin, data=donnees, method='POST', headers=entetes)
    with urllib.request.urlopen(requete, timeout=8) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def _texte_erreur(e):
    if isinstance(e, urllib.error.HTTPError):
        return 'refus %s' % e.code
    if isinstance(e, RuntimeError):
        return str(e)[:80]
    return 'erreur'


def projet_connu():
    try:
        j = jeton()
        if not j:
            raise ValueError('Session absente')
        requete = urllib.request.Request(URL + 'api/state', headers={'X-MC-Token': j})
        with urllib.request.urlopen(requete, timeout=4) as r:
            etat = json.loads(r.read().decode('utf-8', 'replace'))
        projets = etat.get('projects') or []
        projet = projets[0][0]
        if type(projet) is not int or projet <= 0:
            raise ValueError('Projet invalide')
        return projet
    except Exception as e:
        if isinstance(e, urllib.error.HTTPError):
            e.close()
        raise RuntimeError('Projet indisponible : réessayer après rétablissement du service') from None


def tenter_arret():
    try:
        r = appel('api/mc/shutdown', {'project': projet_connu()}, admin=True)
    except Exception as e:
        return False, 'Le service tourne encore (' + _texte_erreur(e) + ')'
    if not isinstance(r, dict) or r.get('ok') is not True:
        return False, 'Le service tourne encore : arrêt non confirmé'
    return True, 'Arrêt confirmé par le serveur'


def tenter_sauvegarde():
    try:
        r = appel('api/mc/backup', {'project': projet_connu()}, admin=True)
    except Exception as e:
        return False, 'Sauvegarde non confirmée (' + _texte_erreur(e) + ')'
    if not isinstance(r, dict) or not r.get('file'):
        return False, 'Sauvegarde non confirmée'
    return True, 'Sauvegarde : ' + str(r.get('file'))


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
        import tkinter as tk
        self.racine = racine
        self.age = 0
        racine.title('TREDIO Control Center')
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
        ok, message = tenter_sauvegarde()
        self.detail.config(text=message[:120])

    def arreter(self):
        ok, message = tenter_arret()
        self.detail.config(text=message[:120])
        if ok:
            self.statut.config(text='Arrêt confirmé')
            self.racine.after(800, self.racine.destroy)
        else:
            self.statut.config(text='Le service tourne encore', fg='#a33')

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
    import tkinter as tk
    racine = tk.Tk()
    Fenetre(racine)
    racine.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
