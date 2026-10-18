"""Tests HTTP d'integration, sur un serveur isole et une base temporaire.

Aucun acces a la base de travail : MC_DB pointe vers un dossier temporaire et
le test verifie a la fin que bm318d.sqlite3 n'a pas ete modifie.
"""
import hashlib
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

RACINE = Path(os.environ.get('MC_RACINE') or Path(__file__).resolve().parent)
VRAIE_BASE = RACINE / 'bm318d.sqlite3'
PYTHON = sys.executable
passes, echecs = 0, 0
detail_echecs = []


def ok(nom, condition, detail=''):
    global passes, echecs
    if condition:
        passes += 1
        print('  ok    ' + nom)
    else:
        echecs += 1
        detail_echecs.append(nom)
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:300]) if detail != '' else ''))


def port_libre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def preparer_base(chemin):
    """Schema minimal attendu par les deux serveurs (projets, taches, evenements)."""
    c = sqlite3.connect(chemin)
    c.executescript("""
    CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE tasks(id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, priority TEXT, agent TEXT,
                       status TEXT DEFAULT 'todo', created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE events(id INTEGER PRIMARY KEY, project_id INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP,
                        agent TEXT, status TEXT, message TEXT);
    """)
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet A'),(2,'Projet B')")
    c.commit()
    c.close()


def appeler(url, methode='GET', corps=None, entetes=None, taille_forcage=None):
    entetes = dict(entetes or {})
    donnees = None
    if corps is not None:
        donnees = corps if isinstance(corps, (bytes, bytearray)) else json.dumps(corps).encode()
        if not isinstance(corps, (bytes, bytearray)):
            entetes.setdefault('Content-Type', 'application/json')
    if taille_forcage is not None:
        entetes['Content-Length'] = str(taille_forcage)
    requete = urllib.request.Request(url, data=donnees, headers=entetes, method=methode)
    try:
        with urllib.request.urlopen(requete, timeout=10) as r:
            return r.status, r.read().decode('utf-8', 'replace'), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace'), dict(e.headers)


def attendre_serveur(base, delai=20):
    fin = time.time() + delai
    while time.time() < fin:
        try:
            code, _, _ = appeler(base + '/')
            if code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def empreinte(chemin):
    return hashlib.sha256(Path(chemin).read_bytes()).hexdigest()


avec_base = VRAIE_BASE.exists()
avant = empreinte(VRAIE_BASE) if avec_base else None
dossier = tempfile.mkdtemp(prefix='bm318d-http-')
base = Path(dossier) / 'test.sqlite3'
preparer_base(base)
port = port_libre()
base_url = 'http://127.0.0.1:%d' % port

env = dict(os.environ)
env.update({'MC_DB': str(base), 'MC_PORT': str(port), 'MC_RATE_LIMIT': '1000'})
proc = subprocess.Popen([PYTHON, str(RACINE / 'MissionControl.py')], cwd=str(RACINE),
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    ok('le serveur isole demarre', attendre_serveur(base_url), 'pas de reponse sur ' + base_url)

    print('\n=== page et jeton ===')
    code, page, entetes = appeler(base_url + '/')
    ok('la page repond 200', code == 200, code)
    jeton = ''
    debut = page.find('name="mc-token" content="')
    if debut >= 0:
        debut += len('name="mc-token" content="')
        jeton = page[debut:page.find('"', debut)]
    ok('la page contient un jeton de session', len(jeton) >= 20, jeton[:8])
    ok('mission.js et mission.css sont injectes', 'mission.js' in page and 'mission.css' in page)
    ok('X-Content-Type-Options: nosniff', entetes.get('X-Content-Type-Options') == 'nosniff', entetes.get('X-Content-Type-Options'))
    ok('Cache-Control: no-store', entetes.get('Cache-Control') == 'no-store', entetes.get('Cache-Control'))
    ok('le jeton n\'apparait que dans le cookie, pas dans un autre en-tete',
       jeton not in json.dumps({k: v for k, v in entetes.items() if k.lower() != 'set-cookie'}))
    cookie = entetes.get('Set-Cookie', '')
    ok('le cookie de session est HttpOnly et SameSite=Strict',
       'HttpOnly' in cookie and 'SameSite=Strict' in cookie and jeton in cookie, cookie)
    code, _, _ = appeler(base_url + '/api/mc/state?project=1', entetes={'Cookie': 'mc_token=' + jeton})
    ok('le cookie seul suffit pour lire l\'etat', code == 200, code)

    print('\n=== acces refuse sans jeton ===')
    code, corps, _ = appeler(base_url + '/api/mc/state?project=1')
    ok('GET /api/mc/state sans jeton -> 403', code == 403, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', {'project': 1, 'name': 'X', 'role': 'manager'})
    ok('POST sans jeton -> 403', code == 403, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', {'project': 1, 'name': 'X', 'role': 'manager'},
                             {'X-MC-Token': 'mauvais-jeton'})
    ok('POST avec un mauvais jeton -> 403', code == 403, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', {'project': 1, 'name': 'X', 'role': 'manager'},
                             {'X-MC-Token': jeton, 'Origin': 'https://exemple.invalide'})
    ok('POST depuis une origine tierce -> 403', code == 403, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/state')
    ok('GET /api/state (ancienne API) sans jeton -> 403', code == 403, (code, corps[:120]))

    print('\n=== validation stricte ===')
    auth = {'X-MC-Token': jeton}
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', {'project': 1, 'name': 'X', 'role': 'manager'},
                             {**auth, 'Content-Type': 'text/plain'})
    ok('Content-Type non JSON -> 415', code == 415, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', b'x' * 20000, auth)
    ok('corps trop gros -> 400', code == 400, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', {'project': 1, 'name': 'X', 'role': 'pirate'}, auth)
    ok('role inconnu -> 400', code == 400, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', {'project': 999, 'name': 'X', 'role': 'manager'}, auth)
    ok('projet inconnu -> 400', code == 400, (code, corps[:120]))

    print('\n=== isolation des projets ===')
    code, corps, _ = appeler(base_url + '/api/mc/agent', 'POST', {'project': 1, 'name': 'Agent A', 'role': 'manager'}, auth)
    ok('creation d\'un agent dans le projet 1', code == 201, (code, corps[:120]))
    agent_a = json.loads(corps)['id'] if code == 201 else None
    code, corps, _ = appeler(base_url + '/api/mc/state?project=2', entetes=auth)
    etat_b = json.loads(corps)
    ok('le projet 2 ne voit pas l\'agent du projet 1', etat_b['agents'] == [], etat_b['agents'])
    code, corps, _ = appeler(base_url + '/api/mc/assignment/update', 'POST', {'project': 2, 'id': 1, 'status': 'done'}, auth)
    ok('on ne modifie pas une attribution d\'un autre projet', code == 400, (code, corps[:120]))

    print('\n=== niveaux de preuve ===')
    code, corps, _ = appeler(base_url + '/api/mc/mission', 'POST', {'project': 1, 'title': 'M', 'objective': 'O'}, auth)
    mission = json.loads(corps)['id']
    code, corps, _ = appeler(base_url + '/api/mc/assignment', 'POST',
                             {'project': 1, 'mission_id': mission, 'agent_id': agent_a, 'task': 'T'}, auth)
    attribution = json.loads(corps)['id']

    def maj(**champs):
        return appeler(base_url + '/api/mc/assignment/update', 'POST', {'project': 1, 'id': attribution, **champs}, auth)

    code, corps, _ = maj(status='done', result='fait', verification='test')
    ok('« test » sans preuve -> 400', code == 400, (code, corps[:160]))
    code, corps, _ = maj(status='done', result='fait', verification='test',
                         evidence={'command': 'python -c pass'})
    ok('« test » sans code de sortie -> 400', code == 400, (code, corps[:160]))
    code, corps, _ = maj(status='working', verification='human')
    ok('« revu par un humain » sur un travail en cours -> 400', code == 400, (code, corps[:160]))
    code, corps, _ = maj(status='done', result='fait', verification='declared')
    ok('« declare » accepte', code == 201, (code, corps[:160]))
    code, corps, _ = appeler(base_url + '/api/mc/state?project=1', entetes=auth)
    ligne = json.loads(corps)['assignments'][0]
    ok('« declare » laisse verified a 0', ligne['verified'] == 0 and ligne['verification'] == 'declared', ligne)
    code, corps, _ = maj(status='done', result='fait', verification='test',
                         evidence={'command': 'python test_mission_control.py', 'exit_code': 0})
    ok('« test » sans job_id est refusé', code == 400 and 'job' in corps.lower(), (code, corps[:160]))

    print('\n=== modele et jobs ===')
    code, corps, _ = appeler(base_url + '/api/mc/models', entetes=auth)
    modeles = json.loads(corps) if code == 200 else {}
    ok('GET /api/mc/models repond avec la liste', code == 200 and 'models' in modeles, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/job/pause', 'POST', {'project': 1, 'id': 1}, auth)
    ok('pause sur un job inexistant -> 400', code == 400, (code, corps[:120]))
    code, corps, _ = appeler(base_url + '/api/mc/job/pause', 'POST', {'project': 1, 'id': 1})
    ok('pause sans jeton -> 403', code == 403, code)

    print('\n=== ancienne API (interface Railway) ===')
    code, corps, _ = appeler(base_url + '/api/task', 'POST', {'project': 1, 'title': 'Tache historique'}, auth)
    ok('POST /api/task fonctionne avec le jeton', code == 201, (code, corps[:160]))
    code, corps, _ = appeler(base_url + '/api/state', entetes=auth)
    taches = json.loads(corps).get('tasks', [])
    ok('la tache apparait dans /api/state', any(t[2] == 'Tache historique' for t in taches), taches)

    print('\n=== arret propre ===')
    proc.terminate()
    try:
        proc.wait(timeout=10)
        arrete = proc.returncode is not None
    except subprocess.TimeoutExpired:
        arrete = False
        proc.kill()
    ok('le serveur s\'arrete sur demande', arrete, proc.returncode)

    print('\n=== limite de debit (serveur dedie, 3/minute) ===')
    port2 = port_libre()
    base2 = 'http://127.0.0.1:%d' % port2
    env2 = dict(env)
    env2.update({'MC_PORT': str(port2), 'MC_RATE_LIMIT': '3'})
    proc2 = subprocess.Popen([PYTHON, str(RACINE / 'MissionControl.py')], cwd=str(RACINE),
                             env=env2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        demarre = attendre_serveur(base2)
        ok('le second serveur isole demarre', demarre)
        jeton2 = ''
        if demarre:
            _, page2, _ = appeler(base2 + '/')
            d2 = page2.find('name="mc-token" content="')
            jeton2 = page2[d2 + len('name="mc-token" content="'):page2.find('"', d2 + len('name="mc-token" content="'))]
        auth2 = {'X-MC-Token': jeton2}
        codes = []
        retry_apres = None
        for i in range(5):
            code, _, entetes_reponse = appeler(base2 + '/api/mc/note', 'POST',
                                               {'project': 1, 'scope': 'project', 'content': 'note %d' % i}, auth2)
            codes.append(code)
            if code == 429:
                retry_apres = entetes_reponse.get('Retry-After')
        ok('les 3 premieres passent', codes[:3] == [201, 201, 201], codes)
        ok('la 4e est refusee en 429', codes[3:].count(429) >= 1, codes)
        ok('la reponse 429 annonce Retry-After', retry_apres == '60', retry_apres)
    finally:
        proc2.terminate()
        try:
            proc2.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc2.kill()
finally:
    if proc.poll() is None:
        proc.kill()
    sortie = proc.stdout.read() if proc.stdout else ''
    if 'Traceback' in sortie:
        print('\n--- sortie du serveur ---\n' + sortie[-2000:])

if avec_base:
    ok('la base de travail est intacte', empreinte(VRAIE_BASE) == avant, 'bm318d.sqlite3 a change')

print('\n%d ok, %d echec(s)' % (passes, echecs))
if detail_echecs:
    print('echecs : ' + ', '.join(detail_echecs))
sys.exit(1 if echecs else 0)
