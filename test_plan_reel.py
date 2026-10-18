"""Test réel P2 : un vrai modèle décompose un objectif, le plan est validé puis appliqué.

Lent et dépendant d'Ollama : séparé de la suite rapide. Base et workspaces temporaires.
Sortie 3 = non exécuté (Ollama indisponible ou réponse inexploitable) : ce test ne
prouve alors rien, et le dit.
"""
import json
import os
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE))
import MissionControl as mc
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
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:400]) if detail != '' else ''))


try:
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as r:
        modeles = [m['name'] for m in json.load(r).get('models', [])]
except Exception as e:
    print('Ollama indisponible : ' + str(e))
    sys.exit(3)
modele = 'qwen-test:latest' if 'qwen-test:latest' in modeles else (modeles[0] if modeles else '')
if not modele:
    print('Aucun modèle installé')
    sys.exit(3)

dossier = Path(tempfile.mkdtemp(prefix='bm318d-plan-reel-'))
mc.DB = dossier / 'plan.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Plan reel')")
mc.init()
mc.job_en_arriere = lambda i, genere=None: None


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


for nom, role in (('Dev', 'backend'), ('Testeur', 'tester')):
    appel('/api/mc/agent', name=nom, role=role)
appel('/api/mc/agent/update', id=1, model=modele)
mission = appel('/api/mc/mission', title='Calculatrice', objective='fournir une fonction somme testée')['id']

objectif = ('Je veux une fonction somme(a, b) dans calcul.py, et un test unitaire qui vérifie '
            'somme(2, 3) == 5. Le test doit être écrit par le testeur.')

print('=== décomposition réelle par %s ===' % modele)
try:
    with mc.connect() as c:
        proposition = mc.plan_proposer(c, 1, {'objective': objectif, 'mission_id': mission, 'model': modele})
except mc_plan.PlanInvalide as e:
    print('NON EXÉCUTÉ : le modèle n\'a pas produit un plan valide -> ' + str(e))
    print('(le plan est refusé, rien n\'est créé : c\'est le comportement attendu, mais le test ne prouve rien)')
    sys.exit(3)

plan = proposition['plan']
print(json.dumps(plan, ensure_ascii=False, indent=1)[:1500])
ok('le modèle a produit un plan valide', len(plan['tasks']) >= 1, plan)
ok('les rôles demandés sont couverts',
   {t['role'] for t in plan['tasks']} <= set(mc_plan.ROLES), plan)
ok('chaque tâche a un agent proposé',
   all(v['agent_id'] for v in proposition['assignations'].values()), proposition['assignations'])

with mc.connect() as c:
    applique = mc.plan_appliquer(c, 1, {'id': proposition['id']})
jobs = applique['jobs']
ok('le plan devient des jobs', len(jobs) == len(plan['tasks']), jobs)
with mc.connect() as c:
    dependances = mc.rows(c, 'SELECT job_id,depends_on FROM mc_job_deps')
ok('les dépendances sont conservées', len(dependances) == sum(len(t['depends_on']) for t in plan['tasks']), dependances)

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
