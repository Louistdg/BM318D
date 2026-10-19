"""Une déclaration ne peut pas imiter un test exécuté.

Échoue si assignment/update accepte un code de sortie ou une commande
différents de la preuve enregistrée par le serveur sur le job cité,
ou si le client peut poser verification=validated lui-même.
"""
import json
import sqlite3
import tempfile
from pathlib import Path

from test_support_v23 import broker_fixture
import MissionControl as mc

_BROKER = broker_fixture(mc)
_BROKER.__enter__()

passes, echecs = 0, 0

def ok(nom, condition, detail=''):
    global passes, echecs
    if condition:
        passes += 1
        print('  ok    ' + nom)
    else:
        echecs += 1
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:300]) if detail != '' else ''))

def refuse(nom, fonction, extrait):
    try:
        fonction()
        ok(nom, False, 'accepté à tort')
    except (ValueError, PermissionError) as e:
        ok(nom, extrait.lower() in str(e).lower(), str(e))

dossier = Path(tempfile.mkdtemp(prefix='dioptre-preuves-'))
mc.DB = dossier / 'preuves.sqlite3'
mc.ROOT = dossier
with sqlite3.connect(mc.DB) as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Preuves')")
mc.init()

def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})

agent = appel('/api/mc/agent', name='Dev', role='backend', team='Backend')['id']
mission = appel('/api/mc/mission', title='M', objective='O')['id']
attribution = appel('/api/mc/assignment', mission_id=mission, agent_id=agent, task='T')['id']
job = appel('/api/mc/job', agent_id=agent, assignment_id=attribution, title='Job', task='x')['id']
stockee = {'command': 'python -m unittest -v', 'exit_code': 1, 'job_id': job, 'stdout': 'reel'}
with mc.connect() as c:
    c.execute("UPDATE mc_jobs SET status='approved', evidence=? WHERE id=?", (json.dumps(stockee), job))

print('=== déclaration manuelle !== preuve exécutée ===')
refuse('exit_code inventé refusé', lambda: appel(
    '/api/mc/assignment/update', id=attribution, status='reviewed', verification='test',
    evidence={'command': 'python -m unittest -v', 'exit_code': 0, 'job_id': job}), 'différent')
refuse('commande inventée refusée', lambda: appel(
    '/api/mc/assignment/update', id=attribution, status='reviewed', verification='test',
    evidence={'command': 'python -c pass', 'exit_code': 1, 'job_id': job}), 'différent')
refuse('validated ne se déclare pas', lambda: appel(
    '/api/mc/assignment/update', id=attribution, status='reviewed', verification='validated',
    evidence=stockee), 'serveur')

resultat = appel('/api/mc/assignment/update', id=attribution, status='reviewed', verification='test',
                 evidence={**stockee, 'forge': True}, verified_by='pirate')
ok('la preuve conforme est acceptée', resultat.get('verification') == 'test', resultat)
with mc.connect() as c:
    ligne = c.execute('SELECT verification,evidence,verified_by FROM mc_assignments WHERE id=?', (attribution,)).fetchone()
ok('la preuve stockée est celle du serveur, pas le JSON client', json.loads(ligne['evidence']) == stockee, ligne['evidence'])
ok('verified_by ignore le client et note le principal', ligne['verified_by'] == 'admin', ligne['verified_by'])

humain = appel('/api/mc/assignment/update', id=attribution, status='reviewed', verification='human', result='relu', verified_by='pirate')
with mc.connect() as c:
    ligne = c.execute('SELECT verification,verified_by FROM mc_assignments WHERE id=?', (attribution,)).fetchone()
ok('une revue humaine reste distincte d\'un test', ligne['verification'] == 'human', ligne['verification'])
ok('la revue humaine enregistre le principal, pas le nom envoyé', ligne['verified_by'] == 'admin', ligne['verified_by'])

print('\n%d ok, %d echec(s)' % (passes, echecs))
raise SystemExit(1 if echecs else 0)
