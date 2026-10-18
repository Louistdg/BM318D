"""Tests P2 : planification, dÃ©pendances, orchestration, charge.

Le modÃ¨le est simulÃ© : aucun appel rÃ©seau. Les workspaces sont temporaires.
"""
import json
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


dossier = Path(tempfile.mkdtemp(prefix='bm318d-plan-'))
mc.DB = dossier / 'plan.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet plan'),(2,'Autre')")
mc.init()
# Aucune gÃ©nÃ©ration rÃ©elle : les lancements ne doivent pas appeler Ollama.
mc.job_en_arriere = lambda i, genere=None: None


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


backend1 = appel('/api/mc/agent', name='Dev 1', role='backend')['id']
backend2 = appel('/api/mc/agent', name='Dev 2', role='backend')['id']
tester = appel('/api/mc/agent', name='Testeur', role='tester')['id']
mission = appel('/api/mc/mission', title='Mission P2', objective='Livrer une fonctionnalite')['id']

plan_valide = {
    'objective': 'Livrer une fonctionnalite',
    'tasks': [
        {'title': 'Ecrire le module', 'task': 'calcul.py avec somme', 'role': 'backend', 'depends_on': []},
        {'title': 'Ecrire les tests', 'task': 'test_calcul.py', 'role': 'tester', 'depends_on': [0]},
        {'title': 'Documenter', 'task': 'README', 'role': 'backend', 'depends_on': [0, 1]},
    ],
}


def generer(plan):
    return lambda modele, tache, contexte: plan


print('=== proposition de plan ===')
resultat = appel('/api/mc/plan', objective='Livrer une fonctionnalite', mission_id=mission,
                 genere=generer(plan_valide)) if False else None
# L'injection passe par plan_proposer : on l'appelle directement avec la connexion.
with mc.connect() as c:
    proposition = mc.plan_proposer(c, 1, {'objective': 'Livrer une fonctionnalite', 'mission_id': mission},
                                   genere=generer(plan_valide))
plan_id = proposition['id']
ok('le plan est enregistre', isinstance(plan_id, int) and plan_id > 0)
ok('le plan contient 3 taches', len(proposition['plan']['tasks']) == 3, proposition['plan'])
ok('chaque tache a un agent par role',
   [proposition['assignations'][str(i)]['role'] for i in range(3)] == ['backend', 'tester', 'backend'],
   proposition['assignations'])
ok('la tache backend va au moins charge (Dev 1)', proposition['assignations']['0']['agent_id'] == backend1,
   proposition['assignations']['0'])
ok('aucun role sans agent', proposition['roles_sans_agent'] == [], proposition['roles_sans_agent'])

print('\n=== plans refuses ===')
def refuse(nom, plan, motif):
    try:
        mc_plan.valider_plan(plan)
        ok(nom, False, 'accepte a tort')
    except mc_plan.PlanInvalide as e:
        ok(nom, motif in str(e), str(e))

refuse('plus de 8 taches refuse', {'objective': 'x', 'tasks': [{'title': str(i), 'task': 't', 'role': 'backend'} for i in range(9)]}, 'Trop de tâches')
refuse('role inconnu refuse', {'objective': 'x', 'tasks': [{'title': 'a', 'task': 't', 'role': 'pirate'}]}, 'rôle inconnu')
refuse('cycle refuse', {'objective': 'x', 'tasks': [
    {'title': 'a', 'task': 't', 'role': 'backend', 'depends_on': [1]},
    {'title': 'b', 'task': 't', 'role': 'backend', 'depends_on': [0]}]}, 'circulaires')
refuse('dependance hors bornes refusee', {'objective': 'x', 'tasks': [
    {'title': 'a', 'task': 't', 'role': 'backend', 'depends_on': [3]}]}, 'invalide')
refuse('plan vide refuse', {'objective': 'x', 'tasks': []}, 'Aucune tâche')

print('\n=== application du plan ===')
with mc.connect() as c:
    applique = mc.plan_appliquer(c, 1, {'id': plan_id})
jobs = applique['jobs']
ok('trois jobs sont crees', len(jobs) == 3, jobs)
with mc.connect() as c:
    dependances = mc.rows(c, 'SELECT job_id,depends_on FROM mc_job_deps ORDER BY job_id')
    liasse = mc.job_publie(c, 1, jobs['1'])
ok('les dependances sont enregistrees', len(dependances) == 3, dependances)
ok('le job 2 attend le job 1', {'job_id': jobs['1'], 'depends_on': jobs['0']} in dependances, dependances)
ok('le job de test est attribue au testeur', liasse['agent_id'] == tester, liasse['agent_id'])
with mc.connect() as c:
    try:
        mc.plan_appliquer(c, 1, {'id': plan_id})
        ok('un plan ne s\'applique pas deux fois', False)
    except ValueError:
        ok('un plan ne s\'applique pas deux fois', True)

print('\n=== dependances a l\'execution ===')
with mc.connect() as c:
    bloque = mc.job_lancer(c, 1, jobs['1'])
    etat = mc.job_publie(c, 1, jobs['1'])
ok('le job 2 est bloque tant que le job 1 n\'est pas approuve', etat['status'] == 'blocked', (bloque, etat['status']))
with mc.connect() as c:
    mc.job_executer(jobs['0'], generer({'files': [{'path': 'calcul.py', 'content': 'def somme(a,b):\n    return a+b\n'}]}))
    mc.job_approuver(c, 1, jobs['0'], {'agent_id': backend1})
with mc.connect() as c:
    mc.job_lancer(c, 1, jobs['1'])
    etat2 = mc.job_publie(c, 1, jobs['1'])
ok('le prerequis approuve debloque le job 2', etat2['status'] in ('queued', 'running'), etat2['status'])

print('\n=== orchestrateur et limite de charge ===')
os.environ['MC_MAX_JOBS'] = '1'
ok('la limite suit MC_MAX_JOBS', mc_plan.executions_simultanees() == 1, mc_plan.executions_simultanees())
with mc.connect() as c:
    # Un job en cours occupe la seule place.
    c.execute("UPDATE mc_jobs SET status='running' WHERE id=?", (jobs['1'],))
    bilan = mc.orchestrateur_lancer(c, 1, {})
ok('aucun lancement quand la limite est atteinte', bilan['lances'] == [], bilan)
ok('le bilan annonce la limite', bilan['limite'] == 1, bilan)
with mc.connect() as c:
    c.execute("UPDATE mc_jobs SET status='queued' WHERE id=?", (jobs['1'],))
    bilan2 = mc.orchestrateur_lancer(c, 1, {})
ok('un job pret est lance quand une place se libere', jobs['1'] in bilan2['lances'], bilan2)
os.environ.pop('MC_MAX_JOBS')

print('\n=== memoire et charge ===')
libre = mc_plan.memoire_libre_mo()
ok('la memoire libre est mesuree', isinstance(libre, int) and libre > 0, libre)
with mc.connect() as c:
    charge = mc.charge_agents(c, 1)
ok('la charge liste les agents', len(charge['agents']) == 3, charge['agents'])
ok('la charge donne une memoire libre', isinstance(charge['memoire_libre_mo'], int), charge['memoire_libre_mo'])
ok('la charge donne une limite d\'executions', charge['limite'] >= 1, charge['limite'])

print('\n=== suggestion de reaffectation ===')
with mc.connect() as c:
    c.execute("UPDATE mc_jobs SET status='failed',error='panne' WHERE id=?", (jobs['0'],))
    charge2 = mc.charge_agents(c, 1)
ok('une reaffectation est proposee pour un job en echec', len(charge2['suggestions']) == 1, charge2['suggestions'])
if charge2['suggestions']:
    suggestion = charge2['suggestions'][0]
    ok('la suggestion vise un agent du meme role', suggestion['vers_id'] == backend2, suggestion)
    ok('la suggestion nomme l\'agent actuel', suggestion['agent_actuel'] == 'Dev 1', suggestion)

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
