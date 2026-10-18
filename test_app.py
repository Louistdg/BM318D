"""Tests P7 : réglages, recherche, notifications, historique, sauvegardes,
restauration, arrêt propre, installateur.

Base temporaire. Le serveur réel n'est pas touché (sauf le test d'arrêt, sur un
port libre et une base temporaire).
"""
import importlib.util
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
sys.path.insert(0, str(RACINE))
from test_support_v23 import broker_fixture
import MissionControl as mc
_BROKER_CONTEXT=broker_fixture(mc)
_BROKER_CONTEXT.__enter__()
import mc_agent

passes, echecs = 0, 0


def ok(nom, condition, detail=''):
    global passes, echecs
    if condition:
        passes += 1
        print('  ok    ' + nom)
    else:
        echecs += 1
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:300]) if detail != '' else ''))


dossier = Path(tempfile.mkdtemp(prefix='bm318d-app-'))
mc.DB = dossier / 'app.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
mc.ROOT = dossier  # backups/ et workspaces/ restent dans le dossier temporaire
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet app')")
mc.init()


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


print('=== réglages ===')
with mc.connect() as c:
    defauts = mc.reglages(c, 1)
ok('les réglages par défaut sont fournis', defauts['ollama_url'].startswith('http://127.0.0.1:11434'), defauts)
appel('/api/mc/settings', key='ollama_url', value='http://127.0.0.1:11434/api/chat')
with mc.connect() as c:
    apres = mc.reglages(c, 1)
ok('un réglage est enregistré', apres['ollama_url'].endswith('/api/chat'), apres['ollama_url'])
appel('/api/mc/settings', key='max_jobs', value='2')
ok('max_jobs est appliqué à la variable d\'environnement', os.environ.get('MC_MAX_JOBS') == '2', os.environ.get('MC_MAX_JOBS'))
try:
    appel('/api/mc/settings', key='pirate', value='x')
    ok('un réglage inconnu est refusé', False)
except ValueError:
    ok('un réglage inconnu est refusé', True)

print('\n=== recherche globale ===')
agent = appel('/api/mc/agent', name='Cherchable Alpha', role='backend', team='Backend')['id']
mission = appel('/api/mc/mission', title='Mission Cherchable', objective='objectif unique')['id']
appel('/api/mc/note', scope='project', content='note cherchable sur le stockage')
appel('/api/mc/decision', title='Décision cherchable', decision='on garde SQLite', rationale='simple')
with mc.connect() as c:
    trouve = mc.rechercher(c, 1, 'cherchable')
ok('la recherche trouve les agents', any(a['name'] == 'Cherchable Alpha' for a in trouve['agents']), trouve['agents'])
ok('la recherche trouve les missions', any(m['title'] == 'Mission Cherchable' for m in trouve['missions']))
ok('la recherche trouve les notes', len(trouve['notes']) >= 1)
ok('la recherche trouve les décisions', len(trouve['decisions']) >= 1)
with mc.connect() as c:
    try:
        mc.rechercher(c, 1, 'a')
        ok('une recherche trop courte est refusée', False)
    except ValueError:
        ok('une recherche trop courte est refusée', True)

print('\n=== notifications et historique ===')
appel('/api/mc/message', from_agent=None, to_agent=agent, body='message a lire')
appel('/api/mc/recruit', name='Recrue attente', role='tester', team='Qualité', justification='charge')
appel('/api/mc/agent/update', id=agent, manager_id=None)
with mc.connect() as c:
    avis = mc.notifications(c, 1)
ok('les messages non lus sont comptés', avis['messages_non_lus'] >= 1, avis)
ok('les recrutements en attente sont comptés', avis['recrutements_en_attente'] >= 1, avis)
ok('les jobs en échec sont comptés', 'jobs_en_echec' in avis, avis)
with mc.connect() as c:
    hist = mc.historique(c, 1)
ok('l\'historique contient le journal d\'audit', len(hist['audit']) >= 5, len(hist['audit']))
ok('l\'historique contient les jobs', 'jobs' in hist)

print('\n=== sauvegardes ===')
manuelle = appel('/api/mc/backup')
ok('une sauvegarde manuelle est écrite', (dossier / 'backups' / manuelle['file']).exists(), manuelle)
with mc.connect() as c:
    liste = mc.sauvegardes_disponibles()
ok('la liste des sauvegardes est lisible', any(b['nom'] == manuelle['file'] for b in liste), liste[:3])
for i in range(12):
    (dossier / 'backups' / ('bm318d-auto-%02d.sqlite3' % i)).write_bytes(b'x')
    (dossier / 'backups' / ('bm318d-auto-%02d.imports.zip' % i)).write_bytes(b'zip-test')
supprimes = mc.rotation_sauvegardes(10)
restants = len(list((dossier / 'backups').glob('bm318d-auto-*.sqlite3')))
ok('la rotation ne garde que 10 sauvegardes automatiques', restants == 10 and supprimes == 2, {'restants': restants, 'supprimes': supprimes})
archives = len(list((dossier / 'backups').glob('bm318d-auto-*.imports.zip')))
ok('la rotation garde les archives ZIP associées', archives == 10, archives)

print('\n=== restauration ===')
with mc.connect() as c:
    avant = len(mc.rows(c, 'SELECT id FROM mc_agents'))
with mc.connect() as c:
    c.execute('PRAGMA foreign_keys=OFF')
    c.execute('DELETE FROM mc_agents')
with mc.connect() as c:
    vide = len(mc.rows(c, 'SELECT id FROM mc_agents'))
ok('la base a bien été vidée pour le test', vide == 0, vide)
with mc.connect() as c:
    restaure = mc.restaurer_sauvegarde(c, 1, {'file': manuelle['file']})
with mc.connect() as c:
    apres = len(mc.rows(c, 'SELECT id FROM mc_agents'))
ok('la restauration remet les agents', apres == avant, {'avant': avant, 'apres': apres})
ok('une sauvegarde de sécurité est faite avant restauration', (dossier / 'backups' / restaure['sauvegarde_prealable']).exists(), restaure)
try:
    with mc.connect() as c:
        mc.restaurer_sauvegarde(c, 1, {'file': '../app.sqlite3'})
    ok('on ne restaure pas un fichier hors de backups/', False)
except ValueError:
    ok('on ne restaure pas un fichier hors de backups/', True)

print('\n=== installateur ===')
cible = dossier / 'installation'
script = RACINE / 'installer' / 'BM318d-Setup.ps1'
resultat = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                           '-TargetDir', str(cible), '-NoShortcuts'],
                          capture_output=True, text=True, timeout=120)
ok('l\'installateur s\'exécute', resultat.returncode == 0, resultat.stderr[-300:])
ok('les fichiers du serveur sont installés', (cible / 'MissionControl.py').exists() and (cible / 'mc_agent.py').exists())
ok('le lanceur est créé', (cible / 'LANCER-BM318d.cmd').exists())
ok('l\'arrêt est créé', (cible / 'ARRETER-BM318d.cmd').exists())
ok('le désinstalleur est créé', (cible / 'desinstaller.ps1').exists())
ok('le dossier de sauvegardes est créé', (cible / 'backups').is_dir())

print('\n=== arrêt propre (serveur réel isolé) ===')
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
url = 'http://127.0.0.1:%d/' % port
env = dict(os.environ)
env.update({'MC_DB': str(dossier / 'arret.sqlite3'), 'MC_PORT': str(port), 'MC_WORKSPACES': str(dossier / 'ws-arret')})
base_arret = Path(env['MC_DB'])
c = sqlite3.connect(base_arret)
c.executescript("""
CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE tasks(id INTEGER PRIMARY KEY,project_id INTEGER,title TEXT,priority TEXT,agent TEXT,status TEXT,created TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY,project_id INTEGER,created TEXT,agent TEXT,status TEXT,message TEXT);
INSERT INTO projects(id,name) VALUES(1,'Arret');
""")
c.commit()
c.close()
serveur = subprocess.Popen([sys.executable, str(RACINE / 'MissionControl.py')], cwd=str(RACINE), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    pret = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    pret = True
                    break
        except Exception:
            time.sleep(0.25)
    ok('le serveur isolé démarre', pret)
    with urllib.request.urlopen(url, timeout=5) as r:
        html = r.read().decode('utf-8')
    import re
    jeton = re.search(r'name="mc-token" content="([^"]+)"', html).group(1)
    entetes_jeton = {'X-MC-Token': jeton}
    with urllib.request.urlopen(urllib.request.Request(url + 'api/mc/version', headers=entetes_jeton), timeout=5) as r:
        version = json.loads(r.read().decode('utf-8'))
    ok('le serveur annonce sa version', version.get('version') == mc.VERSION, version)
    with urllib.request.urlopen(urllib.request.Request(url + 'api/mc/update/check', headers=entetes_jeton), timeout=5) as r:
        maj = json.loads(r.read().decode('utf-8'))
    ok('la vérification de mise à jour répond', 'a_jour' in maj and 'proposee' in maj, maj)

    # Fenêtre de contrôle : mêmes appels, sans ouvrir de fenêtre.
    os.environ['MC_PORT'] = str(port)
    spec_f = importlib.util.spec_from_file_location('fenetre', RACINE / 'BM318d-Fenetre.pyw')
    fenetre = importlib.util.module_from_spec(spec_f)
    spec_f.loader.exec_module(fenetre)
    ok('la fenêtre de contrôle voit le service en ligne', fenetre.en_ligne() is True)
    ok('la fenêtre lit le jeton de la page', isinstance(fenetre.jeton(), str) and len(fenetre.jeton()) > 10)
    os.environ.pop('MC_PORT', None)

    fichier_admin = base_arret.parent / 'logs' / 'admin-token.txt'
    jeton_admin = fichier_admin.read_text(encoding='utf-8') if fichier_admin.exists() else ''
    requete = urllib.request.Request(url + 'api/mc/shutdown', data=b'{"project":1}',
                                     headers={'Content-Type': 'application/json', 'X-MC-Token': jeton,
                                              'X-MC-Admin': jeton_admin}, method='POST')
    sans_admin = urllib.request.Request(url + 'api/mc/shutdown', data=b'{"project":1}',
                                        headers={'Content-Type': 'application/json', 'X-MC-Token': jeton}, method='POST')
    try:
        urllib.request.urlopen(sans_admin, timeout=5)
        ok('l\'arrêt sans jeton administrateur est refusé', False)
    except urllib.error.HTTPError as e:
        ok('l\'arrêt sans jeton administrateur est refusé', e.code == 403, e.code)
    with urllib.request.urlopen(requete, timeout=5) as r:
        arret = json.loads(r.read().decode('utf-8'))
    ok('l\'arrêt exige et accepte le jeton administrateur', arret.get('ok') is True, arret)
    fini = False
    for _ in range(40):
        if serveur.poll() is not None:
            fini = True
            break
        time.sleep(0.25)
    ok('le processus se termine après l\'arrêt', fini, serveur.poll())
    # Les réglages sur le serveur temporaire ne doivent pas avoir touché la base réelle.
finally:
    if serveur.poll() is None:
        serveur.kill()

print('\n=== dossier des workspaces ===')
nouvel_espace = dossier / 'ws-perso'
appel('/api/mc/settings', key='workspace_dir', value=str(nouvel_espace))
job_ws = appel('/api/mc/job', agent_id=agent, title='Espace perso', task='x')['id']
with mc.connect() as c:
    espace = mc.job_publie(c, 1, job_ws)['workspace']
ok('le dossier des workspaces est appliqué sans redémarrage', str(nouvel_espace.resolve()) in espace, espace)
try:
    appel('/api/mc/settings', key='workspace_dir', value='relatif\\dossier')
    ok('un dossier relatif est refusé', False)
except ValueError:
    ok('un dossier relatif est refusé', True)

print('\n=== mise à jour contrôlée ===')
source_maj = dossier / 'maj-source'
cible_maj = dossier / 'maj-cible'
(source_maj).mkdir(); (cible_maj / 'backups').mkdir(parents=True)
(source_maj / 'MissionControl.py').write_text('VERSION_NOUVELLE = True\n', encoding='utf-8')
(source_maj / 'version.json').write_text('{"version":"2.1.0"}', encoding='utf-8')
(cible_maj / 'MissionControl.py').write_text('VERSION_ANCIENNE = True\n', encoding='utf-8')
script_maj = RACINE / 'installer' / 'BM318d-Update.ps1'
resultat_maj = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script_maj),
                               '-Source', str(source_maj), '-TargetDir', str(cible_maj)],
                              capture_output=True, text=True, timeout=120)
ok('le script de mise à jour s\'exécute', resultat_maj.returncode == 0, resultat_maj.stderr[-300:])
ok('le fichier est remplacé', 'VERSION_NOUVELLE' in (cible_maj / 'MissionControl.py').read_text(encoding='utf-8'))
ok('le manifeste de version suit', (cible_maj / 'version.json').exists())
sauvegardes_maj = list((cible_maj / 'backups').glob('pre-maj-*'))
ok('une sauvegarde pré-mise-à-jour est créée', len(sauvegardes_maj) == 1 and (sauvegardes_maj[0] / 'MissionControl.py').exists(), sauvegardes_maj)

print('\n=== contrôleur ===')
spec = importlib.util.spec_from_file_location('controleur', RACINE / 'BM318d-Controleur.pyw')
controleur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controleur)
ok('le contrôleur sait tester la présence du serveur', callable(controleur.repond))
ok('le contrôleur vise le bon port par défaut', controleur.PORT == 31880, controleur.PORT)

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
