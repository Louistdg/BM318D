"""Arrêt et sauvegarde : aucun succès sans confirmation du serveur.

Serveur isolé, base temporaire. N'imprime aucun jeton.
"""
import importlib.machinery
import importlib.util
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import urllib.request
from pathlib import Path

try:
    import tkinter  # noqa: F401
except Exception:
    sys.modules['tkinter'] = types.ModuleType('tkinter')

RACINE = Path(__file__).resolve().parent


def serveur_repond(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def attendre(url):
    for _ in range(60):
        if serveur_repond(url):
            return True
        time.sleep(0.25)
    return False


def demarrer():
    dossier = Path(tempfile.mkdtemp(prefix='dioptre-arret-'))
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    url = 'http://127.0.0.1:%d/' % port
    base = dossier / 'arret.sqlite3'
    c = sqlite3.connect(base)
    c.executescript("""
    CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
    CREATE TABLE tasks(id INTEGER PRIMARY KEY,project_id INTEGER,title TEXT,priority TEXT,agent TEXT,status TEXT,created TEXT);
    CREATE TABLE events(id INTEGER PRIMARY KEY,project_id INTEGER,created TEXT,agent TEXT,status TEXT,message TEXT);
    INSERT INTO projects(id,name) VALUES(1,'Arret honnete');
    """)
    c.commit()
    c.close()
    env = dict(os.environ)
    env.update({'MC_DB': str(base), 'MC_PORT': str(port), 'MC_WORKSPACES': str(dossier / 'ws')})
    proc = subprocess.Popen([sys.executable, str(RACINE / 'MissionControl.py')], cwd=str(RACINE), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not attendre(url):
        proc.kill()
        raise RuntimeError('serveur temporaire injoignable')
    jeton_admin = (base.parent / 'logs' / 'admin-token.txt').read_text(encoding='utf-8')
    return proc, url, port, dossier, jeton_admin


def charger_fenetre():
    nom = 'fenetre_arret_%d' % time.time_ns()
    loader = importlib.machinery.SourceFileLoader(nom, str(RACINE / 'DIOPTRE-Fenetre.pyw'))
    spec = importlib.util.spec_from_loader(nom, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def secret_absent(texte, secret):
    return secret not in str(texte)


def main():
    echecs = 0

    def ok(nom, condition):
        nonlocal echecs
        if condition:
            print('  ok    ' + nom)
        else:
            echecs += 1
            print('  ECHEC ' + nom)

    proc, url, port, dossier, jeton_admin = demarrer()
    try:
        os.environ['MC_PORT'] = str(port)
        fenetre = charger_fenetre()
        fenetre.PORT = port
        fenetre.URL = url
        fenetre.LOGS = dossier / 'logs'
        if not hasattr(fenetre, 'tenter_arret') or not hasattr(fenetre, 'tenter_sauvegarde'):
            ok('la fenêtre distingue un arrêt confirmé d\'un échec', False)
            return 1
        admin_path = fenetre.LOGS / 'admin-token.txt'
        if admin_path.exists():
            admin_path.unlink()
        resultat = fenetre.tenter_arret()
        ok('sans jeton administrateur, l\'arrêt n\'est pas un succès', isinstance(resultat, tuple) and resultat[0] is False)
        ok('le message dit que le service tourne encore', isinstance(resultat, tuple) and 'tourne' in resultat[1].lower())
        ok('le message d\'échec ne contient pas le jeton', isinstance(resultat, tuple) and secret_absent(resultat[1], jeton_admin))
        ok('le serveur répond encore', serveur_repond(url) and proc.poll() is None)

        sauve = fenetre.tenter_sauvegarde()
        ok('sans jeton administrateur, la sauvegarde n\'est pas un succès', isinstance(sauve, tuple) and sauve[0] is False)
        ok('le message de sauvegarde refusée ne contient pas le jeton', isinstance(sauve, tuple) and secret_absent(sauve[1], jeton_admin))

        admin_path.write_text(jeton_admin, encoding='utf-8')
        avant = set(p.name for p in (RACINE / 'backups').glob('dioptre-*.sqlite3')) if (RACINE / 'backups').exists() else set()
        sauve_ok = fenetre.tenter_sauvegarde()
        ok('la sauvegarde réussit seulement avec une confirmation', isinstance(sauve_ok, tuple) and sauve_ok[0] is True)
        ok('le message de sauvegarde ne contient pas le jeton', isinstance(sauve_ok, tuple) and secret_absent(sauve_ok[1], jeton_admin))
        nouveaux = []
        if (RACINE / 'backups').exists():
            nouveaux = [p for p in (RACINE / 'backups').glob('dioptre-*.sqlite3') if p.name not in avant]
        ok('le fichier annoncé existe', bool(nouveaux) and all(p.is_file() for p in nouveaux))
        for p in nouveaux:
            p.unlink()

        arret = fenetre.tenter_arret()
        ok('avec le jeton local, l\'arrêt est confirmé', isinstance(arret, tuple) and arret[0] is True)
        ok('le message d\'arrêt ne contient pas le jeton', isinstance(arret, tuple) and secret_absent(arret[1], jeton_admin))
        fini = False
        for _ in range(40):
            if proc.poll() is not None:
                fini = True
                break
            time.sleep(0.25)
        ok('le processus s\'arrête après confirmation', fini)
        ok('le serveur ne répond plus', not serveur_repond(url))
    finally:
        if proc.poll() is None:
            proc.kill()
        os.environ.pop('MC_PORT', None)

    proc2, url2, port2, dossier2, jeton2 = demarrer()
    jeton_clone = RACINE / 'logs' / 'admin-token.txt'
    precedent = jeton_clone.read_text(encoding='utf-8') if jeton_clone.exists() else None
    try:
        env = dict(os.environ)
        env['MC_PORT'] = str(port2)
        if jeton_clone.exists():
            jeton_clone.unlink()
        refuse = subprocess.run([sys.executable, str(RACINE / 'DIOPTRE-Stop.py')], cwd=str(RACINE), env=env,
                                capture_output=True, text=True, timeout=20)
        ok('Stop.py sans jeton administrateur échoue', refuse.returncode == 1)
        ok('Stop.py ne confirme pas l\'arrêt', 'confirm' not in (refuse.stdout or '').lower() or 'non confirm' in (refuse.stdout or '').lower())
        ok('la sortie de Stop.py ne contient pas le jeton', secret_absent(refuse.stdout + refuse.stderr, jeton2))
        ok('le service tourne encore après le refus', serveur_repond(url2) and proc2.poll() is None)
        jeton_clone.parent.mkdir(exist_ok=True)
        jeton_clone.write_text(jeton2, encoding='utf-8')
        accepte = subprocess.run([sys.executable, str(RACINE / 'DIOPTRE-Stop.py')], cwd=str(RACINE), env=env,
                                 capture_output=True, text=True, timeout=20)
        ok('Stop.py confirme l\'arrêt quand le fichier local est là', accepte.returncode == 0)
        ok('la sortie de succès ne contient pas le jeton', secret_absent(accepte.stdout + accepte.stderr, jeton2))
        fini2 = False
        for _ in range(40):
            if proc2.poll() is not None:
                fini2 = True
                break
            time.sleep(0.25)
        ok('le processus s\'arrête via Stop.py', fini2)
    finally:
        if proc2.poll() is None:
            proc2.kill()
        if precedent is None:
            jeton_clone.unlink(missing_ok=True)
        else:
            jeton_clone.write_text(precedent, encoding='utf-8')

    print('%d echec(s)' % echecs)
    return 1 if echecs else 0


if __name__ == '__main__':
    sys.exit(main())
