"""Tests du moteur de jobs (P1), avec un modele simule.

Aucun appel a Ollama : la generation est injectee. Les workspaces sont crees
dans un dossier temporaire, jamais dans le dossier du projet.
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


dossier = Path(tempfile.mkdtemp(prefix='bm318d-jobs-'))
mc.DB = dossier / 'jobs.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet jobs'),(2,'Autre projet')")
mc.init()


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


agent = appel('/api/mc/agent', name='Dev', role='backend')['id']
mission = appel('/api/mc/mission', title='M', objective='O')['id']
attribution = appel('/api/mc/assignment', mission_id=mission, agent_id=agent, task='Corriger')['id']

bonne = {'summary': 'ajoute calcul', 'files': [{'path': 'calcul.py', 'content': 'def somme(a, b):\n    return a + b\n'}]}


def generer_fixe(proposition):
    return lambda modele, tache, contexte: proposition


print('=== creation et workspace ===')
job = appel('/api/mc/job', agent_id=agent, title='Calcul', task='Ecrire une fonction somme', assignment_id=attribution)
identifiant = job['id']
racine = Path(job['workspace'])
ok('le job est cree', isinstance(identifiant, int) and identifiant > 0)
ok('le workspace est sous le dossier temporaire', dossier in racine.parents, str(racine))
ok('le workspace contient le projet, l\'agent et le job',
   str(racine).endswith('p1\\a%d\\job%d' % (agent, identifiant)) or str(racine).endswith('p1/a%d/job%d' % (agent, identifiant)), str(racine))
ok('le workspace est vide au depart', list(racine.iterdir()) == [], list(racine.iterdir()))

print('\n=== proposition et diff, sans ecriture ===')
mc.job_executer(identifiant, generer_fixe(bonne))
with mc.connect() as c:
    ligne = mc.job_publie(c, 1, identifiant)
ok('le job passe en « proposed »', ligne['status'] == 'proposed', ligne['status'])
ok('le diff est produit', '+def somme' in (ligne['diff'] or ''), (ligne['diff'] or '')[:200])
ok('aucun fichier n\'est ecrit avant approbation', not (racine / 'calcul.py').exists())
ok('la proposition est stockee', json.loads(ligne['proposal'])['summary'] == 'ajoute calcul')

print('\n=== approbation et ecriture ===')
resultat = appel('/api/mc/job/approve', id=identifiant, agent_id=agent)
ecrit = racine / 'calcul.py'
ok('le fichier est ecrit apres approbation', ecrit.exists())
ok('le contenu est celui de la proposition', ecrit.read_text(encoding='utf-8') == bonne['files'][0]['content'])
ok('l\'empreinte sha256 est rendue', len(resultat['fichiers']) == 1 and len(resultat['fichiers'][0]['sha256']) == 64, resultat)
with mc.connect() as c:
    ligne = mc.job_publie(c, 1, identifiant)
ok('le job passe en « approved »', ligne['status'] == 'approved', ligne['status'])
try:
    appel('/api/mc/job/run', id=identifiant)
    ok('un job deja applique ne se relance pas', False)
except ValueError:
    ok('un job deja applique ne se relance pas', True)

print('\n=== refus humain ===')
job2 = appel('/api/mc/job', agent_id=agent, title='Autre', task='Autre')['id']
mc.job_executer(job2, generer_fixe({'files': [{'path': 'autre.py', 'content': 'x = 1\n'}]}))
appel('/api/mc/job/reject', id=job2, reason='Pas convaincu')
with mc.connect() as c:
    lieu2 = Path(mc.job_publie(c, 1, job2)['workspace']) / 'autre.py'
ok('le refus ne cree pas le fichier', not lieu2.exists())
with mc.connect() as c:
    ligne2 = mc.job_publie(c, 1, job2)
ok('le job est « cancelled » apres refus', ligne2['status'] == 'cancelled', ligne2['status'])
try:
    appel('/api/mc/job/approve', id=job2, agent_id=agent)
    ok('approuver un job refuse echoue', False)
except ValueError:
    ok('approuver un job refuse echoue', True)

print('\n=== preuves de test non vides ===')
try:
    appel('/api/mc/job/test', id=identifiant, command='py_compile', agent_id=agent)
    ok('py_compile sans fichier est refusé', False)
except ValueError as e:
    ok('py_compile sans fichier est refusé', 'file' in str(e).lower(), str(e))
try:
    appel('/api/mc/job/test', id=identifiant, command='unittest', agent_id=agent)
    ok('unittest sans fichier de test est refusé', False)
except ValueError as e:
    ok('unittest sans fichier de test est refusé', 'test' in str(e).lower(), str(e))
(racine / 'test_vide.py').write_text('# suite vide\n', encoding='utf-8')
original_executer = mc_agent.executer_commande
mc_agent.executer_commande = lambda *a, **k: {'command':'python -m unittest -v','exit_code':0,'stdout':'','stderr':'Ran 0 tests in 0.000s\nOK','duration_ms':0,'isolement':{}}
preuve_vide = appel('/api/mc/job/test', id=identifiant, command='unittest', agent_id=agent)
ok('suite vide ne produit pas une preuve verte', preuve_vide['evidence']['exit_code'] != 0, preuve_vide)
mc_agent.executer_commande = original_executer
(racine / 'test_vide.py').unlink()

print('\n=== securite des chemins ===')
cas = [
    ('remontee de dossier', {'files': [{'path': '../evasion.py', 'content': 'x=1'}]}, 'Remont'),
    ('chemin absolu', {'files': [{'path': 'C:/Windows/evasion.py', 'content': 'x=1'}]}, 'absolu'),
    ('contenu binaire', {'files': [{'path': 'bin.py', 'content': 'a\x00b'}]}, 'binaire'),
    ('fichier trop gros', {'files': [{'path': 'gros.py', 'content': 'x' * 200001}]}, 'trop gros'),
    ('proposition vide', {'files': []}, 'Aucun fichier'),
]
for nom, proposition, attendu in cas:
    j = appel('/api/mc/job', agent_id=agent, title=nom, task='test')['id']
    mc.job_executer(j, generer_fixe(proposition))
    with mc.connect() as c:
        ligne = mc.job_publie(c, 1, j)
    ok(nom + ' -> refus explicite', ligne['status'] == 'failed' and attendu.lower() in (ligne['error'] or '').lower(),
       (ligne['status'], (ligne['error'] or '')[:120]))
    ok(nom + ' -> rien ecrit hors du workspace', not (dossier / 'evasion.py').exists())

print('\n=== commandes autorisees ===')
autorise = False
try:
    mc_agent.executer_commande(racine, 'rm -rf /')
except mc_agent.Refus:
    autorise = True
ok('une commande hors liste est refusee', autorise)

(racine / 'test_calcul.py').write_text(
    'import unittest\nfrom calcul import somme\n\n'
    'class T(unittest.TestCase):\n'
    '    def test_somme(self):\n'
    '        self.assertEqual(somme(2, 3), 5)\n', encoding='utf-8')
preuve = appel('/api/mc/job/test', id=identifiant, command='unittest', agent_id=agent)
ok('la commande unittest tourne dans le workspace', preuve['evidence']['exit_code'] == 0, preuve['evidence'])
ok('la preuve contient la commande et sa duree', 'unittest' in preuve['evidence']['command'] and preuve['evidence']['duration_ms'] >= 0)

with mc.connect() as c:
    attribution_lue = c.execute('SELECT verification,verified,evidence FROM mc_assignments WHERE id=?', (attribution,)).fetchone()
ok('un test reussi passe l\'attribution en verification « test »', attribution_lue[0] == 'test' and attribution_lue[1] == 1, attribution_lue)
ok('la preuve du test est attachee a l\'attribution', 'unittest' in (attribution_lue[2] or ''))

(racine / 'test_echec.py').write_text(
    'import unittest\n\nclass T(unittest.TestCase):\n    def test_ko(self):\n        self.fail("ko")\n', encoding='utf-8')
preuve_ko = appel('/api/mc/job/test', id=identifiant, command='unittest', agent_id=agent)
ok('un test qui echoue remonte un code non nul', preuve_ko['evidence']['exit_code'] != 0, preuve_ko['evidence']['exit_code'])

print('\n=== annulation ===')
job3 = appel('/api/mc/job', agent_id=agent, title='Annulable', task='x')['id']
mc.job_executer(job3, generer_fixe({'files': [{'path': 'annule.py', 'content': 'x=1'}]}))
appel('/api/mc/job/cancel', id=job3)
with mc.connect() as c:
    ligne3 = mc.job_publie(c, 1, job3)
ok('l\'annulation passe le job en « cancelled »', ligne3['status'] == 'cancelled', ligne3['status'])
ok('l\'annulation ne cree pas le fichier', not (racine / 'annule.py').exists())

print('\n=== isolation des projets ===')
try:
    with mc.connect() as c:
        mc.job_publie(c, 2, identifiant)
    ok('un job du projet 1 est invisible au projet 2', False)
except ValueError:
    ok('un job du projet 1 est invisible au projet 2', True)

print('\n=== pause et reprise ===')
job4 = appel('/api/mc/job', agent_id=agent, title='Pausable', task='x')['id']
mc.job_executer(job4, generer_fixe({'files': [{'path': 'pause.py', 'content': 'x=1\n'}]}))
appel('/api/mc/job/pause', id=job4)
with mc.connect() as c:
    ligne4 = mc.job_publie(c, 1, job4)
ok('un job proposé peut être mis en pause', ligne4['status'] == 'paused', ligne4['status'])
ok('la proposition est conservée pendant la pause', 'pause.py' in (ligne4['proposal'] or ''))
appel('/api/mc/job/resume', id=job4)
with mc.connect() as c:
    ligne4b = mc.job_publie(c, 1, job4)
ok('la reprise remet la proposition sans rappeler le modèle', ligne4b['status'] == 'proposed', ligne4b['status'])
ok('le fichier n\'existait toujours pas avant approbation', not (Path(ligne4b['workspace']) / 'pause.py').exists())

job5 = appel('/api/mc/job', agent_id=agent, title='Pause en cours', task='x')['id']
mc._pauses.add(job5)
mc.job_executer(job5, generer_fixe({'files': [{'path': 'pause2.py', 'content': 'y=2\n'}]}))
with mc.connect() as c:
    ligne5 = mc.job_publie(c, 1, job5)
ok('une pause demandée pendant l\'exécution arrête le job après l\'étape', ligne5['status'] == 'paused', ligne5['status'])
ok('la proposition reçue avant la pause est conservée', 'pause2.py' in (ligne5['proposal'] or ''))

print('\n=== dépendances ===')
jobA = appel('/api/mc/job', agent_id=agent, title='Prérequis', task='x')['id']
jobB = appel('/api/mc/job', agent_id=agent, title='Suite', task='x', depends_on=jobA)['id']
reponse = appel('/api/mc/job/run', id=jobB)
with mc.connect() as c:
    ligneB = mc.job_publie(c, 1, jobB)
ok('un job dont le prérequis n\'est pas approuvé est bloqué', ligneB['status'] == 'blocked', (reponse, ligneB['status']))
ok('le blocage explique la dépendance', 'épendance' in (ligneB['error'] or ''), ligneB['error'])
mc.job_executer(jobA, generer_fixe({'files': [{'path': 'a.py', 'content': 'a=1\n'}]}))
appel('/api/mc/job/approve', id=jobA, agent_id=agent)
mc.job_executer(jobB, generer_fixe({'files': [{'path': 'b.py', 'content': 'b=1\n'}]}))
with mc.connect() as c:
    ligneB2 = mc.job_publie(c, 1, jobB)
ok('le prérequis approuvé débloque la suite', ligneB2['status'] == 'proposed', ligneB2['status'])
# Le lancement réel est neutralisé ici : on vérifie la décision, pas le modèle.
mc.job_en_arriere = lambda i, genere=None: None
jobC = appel('/api/mc/job', agent_id=agent, title='Dépendance satisfaite', task='x', depends_on=jobA)['id']
appel('/api/mc/job/run', id=jobC)
with mc.connect() as c:
    ligneC = mc.job_publie(c, 1, jobC)
ok('un job dont le prérequis est approuvé n\'est pas bloqué', ligneC['status'] == 'queued', ligneC['status'])

print('\n=== journal et contexte ===')
with mc.connect() as c:
    horodatage = mc.job_publie(c, 1, job4)['log']
ok('le journal contient des lignes horodatées', bool(horodatage) and '[' in horodatage and 'pause' in horodatage.lower(), (horodatage or '')[:200])

job6 = appel('/api/mc/job', agent_id=agent, title='Contexte', task='x')['id']
with mc.connect() as c:
    racine6 = Path(mc.job_publie(c, 1, job6)['workspace'])
(racine6 / 'existant.py').write_text('VALEUR_CONNUE = 42\n', encoding='utf-8')
(racine6 / 'test_existant.py').write_text(
    'import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n', encoding='utf-8')
capture = {}
def generer_capture(modele, tache, contexte):
    capture['contexte'] = contexte
    capture['modele'] = modele
    return {'files': [{'path': 'existant.py', 'content': 'VALEUR_CONNUE = 43\n'}]}
mc.job_executer(job6, generer_capture)
ok('le contexte envoyé contient le fichier existant du workspace', 'VALEUR_CONNUE = 42' in capture.get('contexte', ''), capture.get('contexte', '')[:200])
ok('le modèle de l\'agent est transmis au générateur', capture.get('modele') in ('qwen3.5:4b', 'qwen-test:latest'), capture.get('modele'))
with mc.connect() as c:
    diff6 = mc.job_publie(c, 1, job6)['diff']
ok('le diff porte sur le contenu existant', '42' in (diff6 or '') and '43' in (diff6 or ''), (diff6 or '')[:200])
appel('/api/mc/job/approve', id=job6, agent_id=agent)
appel('/api/mc/job/test', id=job6, command='unittest', agent_id=agent)
with mc.connect() as c:
    ligne6 = mc.job_publie(c, 1, job6)
ok('un job approuvé passe en « completed » après un test réussi', ligne6['status'] == 'completed', ligne6['status'])

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
