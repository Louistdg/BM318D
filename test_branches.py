"""Tests P2/P6 : branches par architecte, compétences, mesure CPU/GPU.

Aucun appel réseau. Base temporaire.
"""
import os
import sys
import tempfile
from pathlib import Path

from test_support_v23 import broker_fixture
import MissionControl as mc
_BROKER_CONTEXT=broker_fixture(mc)
_BROKER_CONTEXT.__enter__()
import mc_agent
import mc_plan

passes, echecs = 0, 0


def ok(nom, condition, detail=''):
    global passes, echecs
    if condition:
        passes += 1
        print('  ok    ' + nom)
    else:
        echecs += 1
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:300]) if detail != '' else ''))


dossier = Path(tempfile.mkdtemp(prefix='bm318d-branches-'))
mc.DB = dossier / 'branches.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet branches'),(2,'Autre')")
mc.init()
mc.job_en_arriere = lambda i, genere=None: None


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


archi1 = appel('/api/mc/agent', name='Architecte A', role='architect', team='Conception', skills='api, python')['id']
archi2 = appel('/api/mc/agent', name='Architecte B', role='architect', team='Conception', skills='frontend')['id']
dev1 = appel('/api/mc/agent', name='Dev python', role='backend', team='Backend', skills='python, sqlite')['id']
dev2 = appel('/api/mc/agent', name='Dev front', role='backend', team='Backend', skills='javascript, css')['id']

print('=== branches ===')
b1 = appel('/api/mc/branch', name='api', architect_id=archi1, description='API et base')['id']
b2 = appel('/api/mc/branch', name='interface', architect_id=archi2)['id']
with mc.connect() as c:
    branches = mc.rows(c, 'SELECT * FROM mc_branches ORDER BY id')
ok('deux branches sont créées', len(branches) == 2, branches)
ok('chaque branche a son architecte', {b['architect_id'] for b in branches} == {archi1, archi2}, branches)
appel('/api/mc/branch/update', id=b2, architect_id=archi1)
with mc.connect() as c:
    changee = mc.one(c, 'SELECT architect_id FROM mc_branches WHERE id=?', (b2,))
ok('un architecte peut être remplacé sur une branche', changee['architect_id'] == archi1, changee)
try:
    appel('/api/mc/branch', name='orpheline', architect_id=999)
    ok('une branche avec un architecte inconnu est refusée', False)
except ValueError:
    ok('une branche avec un architecte inconnu est refusée', True)

print('\n=== jobs rattachés à une branche ===')
job1 = appel('/api/mc/job', agent_id=dev1, title='Route API', task='x', branch_id=b1)['id']
with mc.connect() as c:
    ligne = mc.one(c, 'SELECT branch_id FROM mc_jobs WHERE id=?', (job1,))
ok('un job porte sa branche', ligne['branch_id'] == b1, ligne)
try:
    appel('/api/mc/job', agent_id=dev1, title='Branche inconnue', task='x', branch_id=999)
    ok('une branche inconnue est refusée', False)
except ValueError:
    ok('une branche inconnue est refusée', True)
with mc.connect() as c:
    try:
        mc.job_creer(c, 2, {'agent_id': dev1, 'title': 'Autre projet', 'task': 'x', 'branch_id': b1})
        ok('une branche d\'un autre projet est refusée', False)
    except ValueError:
        ok('une branche d\'un autre projet est refusée', True)

print('\n=== compétences ===')
with mc.connect() as c:
    agents = mc.rows(c, 'SELECT * FROM mc_agents WHERE project_id=1')
choisi_python = mc_plan.choisir_agent(agents, 'backend', {}, ['python'])
choisi_css = mc_plan.choisir_agent(agents, 'backend', {}, ['css'])
ok('la compétence oriente l\'affectation (python)', choisi_python['id'] == dev1, choisi_python)
ok('la compétence oriente l\'affectation (css)', choisi_css['id'] == dev2, choisi_css)
choisi_sans = mc_plan.choisir_agent(agents, 'backend', {dev1: 3, dev2: 0}, ['python'])
ok('une compétence commune prime sur la charge', choisi_sans['id'] == dev1, choisi_sans)
choisi_neutre = mc_plan.choisir_agent(agents, 'backend', {dev1: 3, dev2: 0}, [])
ok('sans compétence demandée, le moins chargé gagne', choisi_neutre['id'] == dev2, choisi_neutre)

print('\n=== mesure CPU et GPU ===')
charge_cpu = mc_plan.cpu_charge()
ok('la charge CPU est mesurée', charge_cpu is None or (isinstance(charge_cpu, float) and 0 <= charge_cpu <= 100), charge_cpu)
gpu = mc_plan.gpu_info()
ok('le GPU est soit mesuré, soit absent (jamais inventé)', gpu is None or ('utilisation_pct' in gpu and 'memoire_totale_mo' in gpu), gpu)

print('\n=== limite d\'exécutions selon la charge ===')
os.environ.pop('MC_MAX_JOBS', None)
original_memoire, original_cpu, original_gpu = mc_plan.memoire_libre_mo, mc_plan.cpu_charge, mc_plan.gpu_info
try:
    mc_plan.memoire_libre_mo = lambda: 9000
    mc_plan.cpu_charge = lambda: 10.0
    mc_plan.gpu_info = lambda: None
    ok('machine libre : 3 exécutions', mc_plan.executions_simultanees() == 3, mc_plan.executions_simultanees())
    mc_plan.cpu_charge = lambda: 95.0
    ok('CPU saturé : 1 exécution', mc_plan.executions_simultanees() == 1, mc_plan.executions_simultanees())
    mc_plan.cpu_charge = lambda: 50.0
    mc_plan.gpu_info = lambda: {'utilisation_pct': 90.0, 'memoire_totale_mo': 4096}
    ok('GPU saturé : une exécution en moins', mc_plan.executions_simultanees() == 2, mc_plan.executions_simultanees())
    mc_plan.memoire_libre_mo = lambda: 1000
    ok('mémoire basse : 1 exécution', mc_plan.executions_simultanees() == 1, mc_plan.executions_simultanees())
finally:
    mc_plan.memoire_libre_mo, mc_plan.cpu_charge, mc_plan.gpu_info = original_memoire, original_cpu, original_gpu

print('\n=== tableau de charge ===')
with mc.connect() as c:
    tableau = mc.charge_agents(c, 1)
ok('la charge expose le CPU', 'cpu_pct' in tableau, list(tableau))
ok('la charge expose le GPU', 'gpu' in tableau, list(tableau))
ok('la charge expose les branches par architecte',
   len(tableau['agents']) >= 4, len(tableau['agents']))

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
