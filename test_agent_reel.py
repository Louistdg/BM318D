"""Test reel de l'agent executant : un vrai appel a Ollama, un vrai workspace,
une vraie approbation, un vrai test execute.

Lent (le modele local repond en dizaines de secondes) et dependant d'Ollama :
il est donc separe de la suite rapide. Il travaille sur une base et des
workspaces temporaires, sur un port libre ; la base de travail n'est pas touchee.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent
passes, echecs = 0, 0


def ok(nom, condition, detail=''):
    global passes, echecs
    if condition:
        passes += 1
        print('  ok    ' + nom)
    else:
        echecs += 1
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:400]) if detail != '' else ''))


def port_libre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def requete(url, methode='GET', corps=None, entetes=None):
    donnees = json.dumps(corps).encode() if corps is not None else None
    entetes = dict(entetes or {})
    if corps is not None:
        entetes.setdefault('Content-Type', 'application/json')
    requete = urllib.request.Request(url, data=donnees, headers=entetes, method=methode)
    try:
        with urllib.request.urlopen(requete, timeout=30) as r:
            return r.status, json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8', 'replace'))


# 1. Ollama repond ?
try:
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as r:
        modeles = [m['name'] for m in json.load(r).get('models', [])]
    print('modeles Ollama : ' + ', '.join(modeles))
except Exception as e:
    print('Ollama indisponible : ' + str(e))
    sys.exit(2)

modele = 'qwen-test:latest' if 'qwen-test:latest' in modeles else ('qwen3.5:4b' if 'qwen3.5:4b' in modeles else (modeles[0] if modeles else ''))
if not modele:
    print('Aucun modele installe : test impossible')
    sys.exit(2)

dossier = Path(tempfile.mkdtemp(prefix='bm318d-reel-'))
base = dossier / 'reel.sqlite3'
workspaces = dossier / 'workspaces'
port = port_libre()
url = 'http://127.0.0.1:%d' % port

c = sqlite3.connect(base)
c.executescript("""
CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE tasks(id INTEGER PRIMARY KEY,project_id INTEGER,title TEXT,priority TEXT,agent TEXT,status TEXT,created TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY,project_id INTEGER,created TEXT,agent TEXT,status TEXT,message TEXT);
INSERT INTO projects(id,name) VALUES(1,'Test reel');
""")
c.commit()
c.close()

env = dict(os.environ)
env.update({'MC_DB': str(base), 'MC_PORT': str(port), 'MC_WORKSPACES': str(workspaces),
            'MC_RATE_LIMIT': '1000'})
serveur = subprocess.Popen([sys.executable, str(RACINE / 'MissionControl.py')], cwd=str(RACINE),
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    pret = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + '/', timeout=5) as r:
                if r.status == 200:
                    pret = True
                    break
        except Exception:
            time.sleep(0.25)
    if not pret:
        print('Le serveur isole ne demarre pas')
        sys.exit(1)

    # La page est du HTML : on relit le jeton dans la reponse brute.
    with urllib.request.urlopen(url + '/', timeout=5) as r:
        html = r.read().decode('utf-8')
    debut = html.find('name="mc-token" content="')
    jeton = html[debut + len('name="mc-token" content="'):html.find('"', debut + len('name="mc-token" content="'))]
    auth = {'X-MC-Token': jeton}

    def poster(chemin, corps):
        return requete(url + chemin, 'POST', {'project': 1, **corps}, auth)

    code, agent = poster('/api/mc/agent', {'name': 'Dev reel', 'role': 'backend'})
    agent_id = agent['id']
    # Le modele local le plus rapide mesure sur cette machine.
    poster('/api/mc/agent/update', {'id': agent_id, 'model': modele})
    code, mission = poster('/api/mc/mission', {'title': 'Calcul', 'objective': 'fournir une fonction somme testee'})
    code, attribution = poster('/api/mc/assignment', {'mission_id': mission['id'], 'agent_id': agent_id,
                                                     'task': 'Ecrire calcul.py'})
    code, job = poster('/api/mc/job', {'agent_id': agent_id, 'mission_id': mission['id'],
                                       'assignment_id': attribution['id'],
                                       'title': 'Somme testee',
                                       'task': "Ecris un seul fichier calcul.py contenant une fonction "
                                               "somme(a, b) qui renvoie a + b. Aucun autre fichier."})
    job_id = job['id']
    racine = Path(job['workspace'])
    ok('le job reel est cree', isinstance(job_id, int) and racine.exists(), str(racine))

    print('\n=== appel reel au modele (patience) ===')
    poster('/api/mc/job/run', {'id': job_id})
    etat = None
    for _ in range(900):
        code, s = requete(url + '/api/mc/state?project=1', entetes=auth)
        ligne = [j for j in s['jobs'] if j['id'] == job_id][0]
        etat = ligne['status']
        if etat in ('proposed', 'failed', 'cancelled'):
            break
        time.sleep(1)
    ok('le modele a propose quelque chose (ou echoue proprement)', etat in ('proposed', 'failed'), etat)
    if etat == 'failed':
        erreur = str(ligne['error'])
        print('  erreur du modele : ' + erreur[:400])
        if 'HTTP Error 500' in erreur or 'allocate' in erreur or 'timed out' in erreur:
            print('\nNON EXÉCUTÉ : Ollama n\'a pas pu charger le modèle (mémoire insuffisante ou délai).')
            print('Ce test ne prouve rien dans cet état ; la suite rapide reste valable.')
            sys.exit(3)

    if etat == 'proposed':
        with sqlite3.connect(base) as c:
            diff = c.execute('SELECT diff FROM mc_jobs WHERE id=?', (job_id,)).fetchone()[0]
        print('\n--- diff propose ---\n' + (diff or '')[:1500])
        ok('un diff est propose', bool((diff or '').strip()))
        ok('aucun fichier ecrit avant approbation', list(racine.iterdir()) == [], list(racine.iterdir()))

        code, approuve = poster('/api/mc/job/approve', {'id': job_id, 'agent_id': agent_id})
        ok('l\'approbation ecrit les fichiers', code == 201 and len(approuve.get('fichiers', [])) >= 1, (code, approuve))
        ok('le fichier existe dans le workspace', (racine / 'calcul.py').exists())

        # L'humain ajoute lui-meme le test : le modele ne le fournit pas.
        (racine / 'test_calcul.py').write_text(
            'import unittest\nfrom calcul import somme\n\n'
            'class T(unittest.TestCase):\n'
            '    def test_somme(self):\n'
            '        self.assertEqual(somme(2, 3), 5)\n', encoding='utf-8')
        code, preuve = poster('/api/mc/job/test', {'id': job_id, 'command': 'unittest', 'agent_id': agent_id})
        ev = preuve.get('evidence', {})
        print('\n--- preuve du test ---\ncommande : %s\nexit_code : %s\nduree : %s ms\nsortie :\n%s' % (
            ev.get('command'), ev.get('exit_code'), ev.get('duration_ms'), (ev.get('stderr') or ev.get('stdout') or '')[-800:]))
        ok('le test reel tourne et reussit', ev.get('exit_code') == 0, ev.get('stderr'))
        with sqlite3.connect(base) as c:
            verification, verified, evidence = c.execute(
                'SELECT verification,verified,evidence FROM mc_assignments WHERE id=?', (attribution['id'],)).fetchone()
        ok('l\'attribution passe en verification « test »', verification == 'test' and verified == 1, (verification, verified))
        ok('la preuve est enregistree', 'unittest' in (evidence or ''))
finally:
    serveur.terminate()
    try:
        serveur.wait(timeout=10)
    except subprocess.TimeoutExpired:
        serveur.kill()

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
