"""DIOPTRE V2.1 — tests négatifs de sécurité.

Chaque test démontre qu'un contournement possible avant le durcissement est
maintenant refusé : identité obligatoire, permissions fermées, preuves liées à
un job approuvé, réservation atomique, reprise après crash, refus de troncature,
et isolation système réelle des commandes.
"""
import json
import sys
import tempfile
import threading
import contextvars
import time
from pathlib import Path

from test_support_v23 import broker_fixture
import MissionControl as mc
_BROKER_CONTEXT=broker_fixture(mc)
_BROKER_CONTEXT.__enter__()
import mc_agent
import mc_sandbox

passes, echecs = 0, 0


def ok(nom, condition, detail=''):
    global passes, echecs
    if condition:
        passes += 1
        print('  ok    ' + nom)
    else:
        echecs += 1
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:300]) if detail != '' else ''))


def refuse(nom, fonction, extrait=''):
    try:
        fonction()
        ok(nom, False, 'accepté à tort')
    except (ValueError, mc_agent.Refus) as e:
        ok(nom, extrait.lower() in str(e).lower(), str(e))


dossier = Path(tempfile.mkdtemp(prefix='dioptre-securite-'))
mc.DB = dossier / 'securite.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
mc_sandbox.SANDBOX = dossier / 'sandbox'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Sécurité'),(2,'Autre')")
mc.init()
mc.job_en_arriere = lambda i, genere=None: None


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


def generer(proposition):
    return lambda modele, tache, contexte: proposition


chef = appel('/api/mc/agent', name='Chef', role='manager', team='Direction')['id']
dev = appel('/api/mc/agent', name='Dev', role='backend', team='Backend')['id']
mission = appel('/api/mc/mission', title='M', objective='O')['id']
attribution = appel('/api/mc/assignment', mission_id=mission, agent_id=dev, task='T')['id']


def job_propose(titre='Job'):
    identifiant = appel('/api/mc/job', agent_id=dev, title=titre, task='x', assignment_id=attribution)['id']
    mc.job_executer(identifiant, generer({'files': [{'path': 'module.py', 'content': 'x = 1\n'}]}))
    return identifiant


print('=== identité obligatoire ===')
job = job_propose()
refuse('approuver sans agent est refusé', lambda: appel('/api/mc/job/approve', id=job), 'agent')
refuse('lancer les tests sans agent est refusé', lambda: appel('/api/mc/job/test', id=job, command='unittest'), 'agent')
refuse('valider sans agent est refusé', lambda: appel('/api/mc/job/validate', id=job), 'agent')
refuse('committer sans agent est refusé', lambda: appel('/api/mc/job/commit', id=job), 'agent')

print('\n=== permissions fermées par défaut ===')
with mc.connect() as c:
    ok('une équipe sans ligne de permissions n\'a aucun droit', mc.permission(c, 1, 'Inconnue', 'can_approve_jobs') is False)
    c.execute("UPDATE mc_team_permissions SET can_approve_jobs=0 WHERE project_id=1 AND team='Backend'")
refuse('une équipe sans droit ne peut pas approuver',
       lambda: appel('/api/mc/job/approve', id=job, agent_id=dev), 'droit')
appel('/api/mc/job/approve', id=job, agent_id=chef)

print('\n=== preuves liées à un job approuvé ===')
fausse = {'command': 'python -m unittest -v', 'exit_code': 0}
refuse('une preuve fabriquée sans job_id est refusée',
       lambda: appel('/api/mc/assignment/update', id=attribution, status='reviewed', verification='test', evidence=fausse),
       'job_id')
autre = job_propose('Autre job')
refuse('une preuve d\'un job non appliqué est refusée',
       lambda: appel('/api/mc/assignment/update', id=attribution, status='reviewed', verification='test',
                     evidence={**fausse, 'job_id': autre}), 'appliqué')

print('\n=== tests interdits hors approbation ===')
job_non_approuve = appel('/api/mc/job', agent_id=dev, title='Non approuvé', task='x')['id']
refuse('tester un job en attente est refusé',
       lambda: appel('/api/mc/job/test', id=job_non_approuve, command='unittest', agent_id=chef), 'appliqué')
appel('/api/mc/job/cancel', id=job_non_approuve)
refuse('tester un job annulé est refusé',
       lambda: appel('/api/mc/job/test', id=job_non_approuve, command='unittest', agent_id=chef), 'appliqué')
refuse('refuser un job déjà appliqué est refusé',
       lambda: appel('/api/mc/job/reject', id=job, agent_id=chef), 'appliqué')

print('\n=== validation croisée attribution / agent ===')
autre_agent = appel('/api/mc/agent', name='Dev 2', role='backend', team='Backend')['id']
refuse('un job ne peut pas viser l\'attribution d\'un autre agent',
       lambda: appel('/api/mc/job', agent_id=autre_agent, title='X', task='x', assignment_id=attribution), 'attribution')

print('\n=== réservation atomique ===')
job_course = appel('/api/mc/job', agent_id=dev, title='Course', task='x')['id']
compteur = {'n': 0}
verrou = threading.Lock()


def generateur_lent(modele, tache, contexte):
    with verrou:
        compteur['n'] += 1
    time.sleep(0.4)
    return {'files': [{'path': 'course.py', 'content': 'x = 1\n'}]}


def lancer():
    mc.job_executer(job_course, generateur_lent)


fils = [threading.Thread(target=contextvars.copy_context().run,args=(lancer,)) for _ in range(2)]
for f in fils:
    f.start()
for f in fils:
    f.join()
ok('un seul worker exécute le job malgré deux départs', compteur['n'] == 1, compteur)
deuxieme = mc.job_executer(job_course, generateur_lent)
ok('un job déjà pris est refusé sans relancer le modèle', deuxieme.get('status') == 'deja_pris', deuxieme)

print('\n=== reprise après crash ===')
job_crash = appel('/api/mc/job', agent_id=dev, title='Crash', task='x')['id']
with mc.connect() as c:
    c.execute("UPDATE mc_jobs SET status='running',started_at=CURRENT_TIMESTAMP WHERE id=?", (job_crash,))
mc.init()
with mc.connect() as c:
    apres = mc.job_publie(c, 1, job_crash)
ok('un job resté en cours est marqué en échec au redémarrage',
   apres['status'] == 'failed' and 'redémarrage' in (apres['error'] or ''), (apres['status'], apres['error']))

print('\n=== refus de troncature ===')
job_gros = appel('/api/mc/job', agent_id=dev, title='Gros', task='x')['id']
gros_contenu = 'x = 1\n' * 40000  # ~240 000 caractères, au-delà de la limite
mc.job_executer(job_gros, generer({'files': [{'path': 'gros.py', 'content': gros_contenu}]}))
with mc.connect() as c:
    gros = mc.job_publie(c, 1, job_gros)
ok('une proposition trop grosse est refusée explicitement',
   gros['status'] == 'failed' and ('trop volumineuse' in (gros['error'] or '').lower()
                                   or 'trop gros' in (gros['error'] or '').lower()),
   (gros['status'], (gros['error'] or '')[:120]))
ok('rien n\'est enregistré tronqué', (gros['proposal'] or '') == '' and (gros['diff'] or '') == '', len(gros['proposal'] or ''))

print('\n=== confinement OS et identités V2.3 ===')
import re,subprocess
_BROKER_CONTEXT.__exit__(None,None,None)
result=subprocess.run([sys.executable,'-m','unittest','-v','test_sandbox_v23','test_permissions_v23','test_context_v23'],capture_output=True,text=True,encoding='utf-8',errors='replace',env={**__import__('os').environ,'PYTHONIOENCODING':'utf-8'})
combined=result.stdout+result.stderr
print(combined)
count=re.search(r'Ran (\d+) tests?',combined)
verified=result.returncode==0 and bool(count) and bool(re.search(r'^OK$',combined,re.M))
if verified:passes+=int(count[1])
else:echecs+=1
print('\n%d ok, %d echec(s)'%(passes,echecs))
sys.exit(1 if echecs else 0)
