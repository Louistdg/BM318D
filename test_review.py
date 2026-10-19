"""Tests P5 : revue de code, audit de sécurité, validation, commit Git, rapport.

Modèle simulé, workspaces temporaires, vrai git local.
"""
import json
import sys
import tempfile
from pathlib import Path

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


dossier = Path(tempfile.mkdtemp(prefix='bm318d-revue-'))
mc.DB = dossier / 'revue.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet revue'),(2,'Autre')")
mc.init()


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


def generer(proposition):
    return lambda modele, tache, contexte: proposition


agent = appel('/api/mc/agent', name='Revue', role='auditor')['id']
agent2 = appel('/api/mc/agent', name='Testeur', role='tester')['id']
mission = appel('/api/mc/mission', title='M', objective='O')['id']
attribution = appel('/api/mc/assignment', mission_id=mission, agent_id=agent, task='T')['id']


def nouveau_job(contenu):
    job = appel('/api/mc/job', agent_id=agent, title='Job revue', task='x', assignment_id=attribution)['id']
    mc.job_executer(job, generer({'files': [{'path': 'module.py', 'content': contenu}]}))
    return job


print('=== revue impossible avant application ===')
job = nouveau_job('def f():\n    return 1\n')
try:
    appel('/api/mc/review', job_id=job, agent_id=agent, kind='code', verdict='ok')
    ok('on ne révise pas un travail non appliqué', False)
except ValueError:
    ok('on ne révise pas un travail non appliqué', True)
appel('/api/mc/job/approve', id=job, agent_id=agent)

print('\n=== audit de sécurité ===')
propre = appel('/api/mc/review', job_id=job, agent_id=agent, kind='securite')
ok('un diff propre passe l\'audit', propre['verdict'] == 'ok' and propre['findings'] == [], propre)

job2 = nouveau_job('import subprocess\n\ndef f():\n    subprocess.run("dir", shell=True)\n')
appel('/api/mc/job/approve', id=job2, agent_id=agent)
audit = appel('/api/mc/review', job_id=job2, agent_id=agent, kind='securite')
ok('un shell=True est signalé', audit['verdict'] == 'probleme' and len(audit['findings']) >= 1, audit)
ok('le constat nomme le fichier et la ligne', any(c['fichier'] == 'module.py' and c['ligne'] > 0 for c in audit['findings']), audit['findings'])

constats = mc_agent.analyser_diff('+++ b/x.py\n@@ -0,0 +1,2 @@\n+eval("1+1")\n+ok = True\n')
ok('eval est détecté', len(constats) == 1 and 'eval' in constats[0]['probleme'], constats)
ok('un diff sain ne produit aucun constat', mc_agent.analyser_diff('+++ b/x.py\n+print(1)\n') == [])
js_constats=mc_agent.analyser_diff('+++ b/x.js\n@@ -0,0 +1,2 @@\n+node.innerHTML = value\n+require(\"child_process\").execSync(\"whoami\")\n')
ok('la revue de motifs signale les risques JavaScript', any('innerHTML' in x['probleme'] for x in js_constats) and any('Node.js' in x['probleme'] for x in js_constats), js_constats)

print('\n=== revue de code et validation ===')
revue = appel('/api/mc/review', job_id=job, agent_id=agent2, kind='code', verdict='ok', findings=['RAS'])
ok('une revue de code est enregistrée', revue['verdict'] == 'ok', revue)
try:
    appel('/api/mc/job/validate', id=job, agent_id=agent)
    ok('validation refusée sans test exécuté', False)
except ValueError as e:
    ok('validation refusée sans test exécuté', 'test' in str(e).lower(), str(e))

with mc.connect() as c:
    racine = Path(mc.job_publie(c, 1, job)['workspace'])
(racine / 'test_module.py').write_text(
    'import unittest\nfrom module import f\n\nclass T(unittest.TestCase):\n    def test_f(self):\n        self.assertEqual(f(), 1)\n', encoding='utf-8')
appel('/api/mc/job/test', id=job, command='unittest', agent_id=agent)
try:
    appel('/api/mc/job/validate', id=job, agent_id=agent)
    ok('validation refusée sans revue humaine des tests', False)
except ValueError as e:
    ok('validation refusée sans revue humaine des tests', 'humaine' in str(e).lower(), str(e))
appel('/api/mc/review', job_id=job, kind='tests', verdict='ok', findings=['Tests examinés par un opérateur'])
resultat = appel('/api/mc/job/validate', id=job, agent_id=agent)
ok('un travail testé et revu est validé', resultat['verification'] == 'validated', resultat)
with mc.connect() as c:
    ligne = c.execute('SELECT verification,verified FROM mc_assignments WHERE id=?', (attribution,)).fetchone()
ok('l\'attribution passe en « validated »', ligne[0] == 'validated' and ligne[1] == 1, ligne)

print('\n=== une revue en échec bloque la validation ===')
job3 = nouveau_job('def g():\n    return 2\n')
appel('/api/mc/job/approve', id=job3, agent_id=agent)
appel('/api/mc/review', job_id=job3, agent_id=agent, kind='code', verdict='probleme', findings=['variable inutilisée'])
with mc.connect() as c:
    racine3 = Path(mc.job_publie(c, 1, job3)['workspace'])
(racine3 / 'test_module.py').write_text('import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n', encoding='utf-8')
appel('/api/mc/job/test', id=job3, command='unittest', agent_id=agent)
try:
    appel('/api/mc/job/validate', id=job3, agent_id=agent)
    ok('une revue « probleme » empêche la validation', False)
except ValueError as e:
    ok('une revue « probleme » empêche la validation', 'code' in str(e), str(e))

print('\n=== commit Git ===')
commit = appel('/api/mc/job/commit', id=job, message='BM318d : module f', agent_id=agent)
ok('un commit est créé', isinstance(commit.get('commit'), str) and len(commit['commit']) == 40, commit)
with mc.connect() as c:
    preuve = json.loads(mc.job_publie(c, 1, job)['evidence'])
ok('le hash est enregistré dans la preuve', preuve.get('commit') == commit['commit'], preuve)
encore = appel('/api/mc/job/commit', id=job, message='sans changement', agent_id=agent)
ok('sans changement, aucun nouveau commit', encore.get('commit') is None, encore)

print('\n=== rapport ===')
with mc.connect() as c:
    rapport = mc.rapport_job(c, 1, job)
ok('le rapport contient la proposition et le diff', bool(rapport['proposal']) and 'module.py' in rapport['diff'])
ok('le rapport contient la preuve du test', rapport['evidence'].get('exit_code') == 0)
ok('le rapport liste les revues', len(rapport['reviews']) >= 2, rapport['reviews'])
ok('le rapport contient le journal', 'validé' in (rapport['log'] or ''), rapport['log'][-120:])

print('\n=== isolation ===')
try:
    with mc.connect() as c:
        mc.rapport_job(c, 2, job)
    ok('le rapport d\'un job reste dans son projet', False)
except ValueError:
    ok('le rapport d\'un job reste dans son projet', True)

print('\n=== rejet du test factice ===')
faux=appel('/api/mc/job',agent_id=agent,title='Seulement test factice',task='Proposition inutile')['id']
contenu_faux=('import unittest\n\nclass Faux(unittest.TestCase):\n'
              '    def test_faux(self):\n        self.assertTrue(True)\n')
mc.job_executer(faux,generer({'files':[{'path':'test_foo.py','content':contenu_faux}]}))
appel('/api/mc/job/approve',id=faux,agent_id=agent)
preuve_fausse=appel('/api/mc/job/test',id=faux,command='unittest',agent_id=agent)
ok('un unittest factice passe effectivement',preuve_fausse['evidence']['exit_code']==0,preuve_fausse)
appel('/api/mc/review',job_id=faux,agent_id=agent2,kind='code',verdict='ok')
appel('/api/mc/review',job_id=faux,kind='tests',verdict='ok')
try:
    appel('/api/mc/job/validate',id=faux,agent_id=agent)
    ok('validation refusée pour job uniquement composé de tests',False)
except ValueError as erreur:
    ok('validation refusée pour job uniquement composé de tests','source' in str(erreur).lower(),str(erreur))

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
