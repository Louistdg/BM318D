"""Tests P6 : rôles personnalisés, duplication, recrutement, équipes, charge.

Aucun appel réseau. Base temporaire.
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


dossier = Path(tempfile.mkdtemp(prefix='dioptre-equipes-'))
mc.DB = dossier / 'equipes.sqlite3'
mc_agent.WORKSPACES = dossier / 'workspaces'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet equipes')")
mc.init()
mc.job_en_arriere = lambda i, genere=None: None


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


def generer(proposition):
    return lambda modele, tache, contexte: proposition


print('=== bibliothèque de rôles ===')
with mc.connect() as c:
    base = mc.roles_projet(c, 1)
ok('les rôles de base sont disponibles', len(base) == 10 and base[0]['builtin'] is True, len(base))
appel('/api/mc/role', key='devops', label='Ingénieur DevOps', description='CI et déploiement')
with mc.connect() as c:
    roles = mc.roles_projet(c, 1)
ok('un rôle personnalisé est ajouté', any(r['key'] == 'devops' and not r['builtin'] for r in roles))
agent = appel('/api/mc/agent', name='Ops', role='devops', team='Infra')['id']
ok('un agent peut porter le rôle personnalisé', isinstance(agent, int))
try:
    appel('/api/mc/agent', name='X', role='inconnu')
    ok('un rôle inconnu reste refusé', False)
except ValueError:
    ok('un rôle inconnu reste refusé', True)
try:
    appel('/api/mc/role', key='backend', label='Doublon')
    ok('on ne redéfinit pas un rôle de base', False)
except ValueError:
    ok('on ne redéfinit pas un rôle de base', True)
try:
    appel('/api/mc/role', key='Pas Valide!', label='x')
    ok('une clé de rôle invalide est refusée', False)
except ValueError:
    ok('une clé de rôle invalide est refusée', True)

print('\n=== duplication ===')
chef = appel('/api/mc/agent', name='Architecte', role='architect', team='Conception', instructions='Concevoir')['id']
appel('/api/mc/agent/update', id=chef, status='paused')
copie = appel('/api/mc/agent/clone', id=chef)
with mc.connect() as c:
    source = mc.agent(c, 1, chef)
    clone = mc.agent(c, 1, copie['id'])
ok('la copie reprend le rôle, l\'équipe et le modèle', clone['role'] == source['role'] and clone['team'] == source['team'] and clone['model'] == source['model'], clone)
ok('la copie reprend les instructions', clone['instructions'] == source['instructions'])
ok('la copie démarre en attente', clone['status'] == 'idle', clone['status'])
ok('la copie est décalée sur le canvas', (clone['x'], clone['y']) != (source['x'], source['y']), (clone['x'], clone['y']))
ok('la copie a un autre identifiant', clone['id'] != source['id'])

print('\n=== recrutement soumis à validation ===')
recrue = appel('/api/mc/recruit', name='Nouveau testeur', role='tester', team='Qualité', justification='Plus de tests avant livraison')
with mc.connect() as c:
    nombre_avant = len(mc.rows(c, 'SELECT id FROM mc_agents'))
    statut = mc.one(c, 'SELECT status FROM mc_recruits WHERE id=?', (recrue['id'],))['status']
ok('une demande de recrutement est en attente', statut == 'pending', statut)
with mc.connect() as c:
    nombre_pendant = len(mc.rows(c, 'SELECT id FROM mc_agents'))
ok('une demande en attente ne crée pas encore d\'agent', nombre_avant == nombre_pendant)
decision = appel('/api/mc/recruit/decide', id=recrue['id'], approve=True)
with mc.connect() as c:
    nouvel = mc.agent(c, 1, decision['agent_id'])
ok('accepter crée l\'agent demandé', nouvel['name'] == 'Nouveau testeur' and nouvel['role'] == 'tester', nouvel)
ok('la justification devient ses instructions', 'Plus de tests' in nouvel['instructions'], nouvel['instructions'])
try:
    appel('/api/mc/recruit/decide', id=recrue['id'], approve=True)
    ok('un recrutement ne se tranche qu\'une fois', False)
except ValueError:
    ok('un recrutement ne se tranche qu\'une fois', True)
refus = appel('/api/mc/recruit', name='Refusé', role='backend', team='Backend', justification='Test de refus')
appel('/api/mc/recruit/decide', id=refus['id'], approve=False)
with mc.connect() as c:
    etat_refus = mc.one(c, 'SELECT status FROM mc_recruits WHERE id=?', (refus['id'],))['status']
    reste = mc.rows(c, "SELECT id FROM mc_agents WHERE name='Refusé'")
ok('refuser ne crée rien', etat_refus == 'rejected' and reste == [], etat_refus)
try:
    appel('/api/mc/recruit', name='Sans raison', role='backend', team='Backend')
    ok('une demande sans justification est refusée', False)
except ValueError:
    ok('une demande sans justification est refusée', True)

print('\n=== archivage ===')
appel('/api/mc/agent/archive', id=agent)
with mc.connect() as c:
    archive = mc.agent(c, 1, agent)
    charge = mc.charge_agents(c, 1)
ok('l\'agent est archivé', archive['status'] == 'archived', archive['status'])
ok('un archivé ne compte plus comme actif', charge['total']['archives'] == 1, charge['total'])
with mc.connect() as c:
    choisi = mc_plan.choisir_agent(mc.rows(c, 'SELECT * FROM mc_agents WHERE project_id=1'), 'devops', {})
ok('un archivé n\'est plus proposé pour une tâche', choisi is None, choisi)

print('\n=== permissions par équipe ===')
appel('/api/mc/permissions', team='Qualité', can_approve_jobs=False, can_run_tests=False, can_create_agents=False)
with mc.connect() as c:
    perms = {p['team']: p for p in mc.permissions_lire(c, 1)}
ok('les permissions sont enregistrées', perms['Qualité']['can_approve_jobs'] is False, perms.get('Qualité'))
ok('les autres équipes gardent leurs droits', perms.get('Conception', {}).get('can_approve_jobs') is True, perms.get('Conception'))

job = appel('/api/mc/job', agent_id=decision['agent_id'], title='Job équipe', task='x')['id']
mc.job_executer(job, generer({'files': [{'path': 'a.py', 'content': 'x=1\n'}]}))
try:
    appel('/api/mc/job/approve', id=job, agent_id=decision['agent_id'])
    ok('une équipe sans droit ne peut pas approuver', False)
except ValueError as e:
    ok('une équipe sans droit ne peut pas approuver', 'droit' in str(e), str(e))
appel('/api/mc/job/approve', id=job, agent_id=chef)
try:
    appel('/api/mc/job/test', id=job, command='unittest', agent_id=decision['agent_id'])
    ok('une équipe sans droit ne peut pas lancer les tests', False)
except ValueError as e:
    ok('une équipe sans droit ne peut pas lancer les tests', 'droit' in str(e), str(e))
try:
    appel('/api/mc/recruit/decide', id=appel('/api/mc/recruit', name='X', role='backend', team='Qualité', justification='x')['id'], approve=True, agent_id=decision['agent_id'])
    ok('une équipe sans droit ne peut pas recruter', False)
except ValueError as e:
    ok('une équipe sans droit ne peut pas recruter', 'droit' in str(e), str(e))

print('\n=== tableau de charge ===')
with mc.connect() as c:
    tableau = mc.charge_agents(c, 1)
ligne = next(a for a in tableau['agents'] if a['id'] == decision['agent_id'])
ok('la charge compte les jobs en échec', 'echecs' in ligne and ligne['echecs'] >= 0, ligne)
ok('la charge dit si l\'agent est disponible', isinstance(ligne['disponible'], bool), ligne)
ok('la charge compte les messages non lus', 'messages_non_lus' in ligne, ligne)
ok('le total donne les archivés', tableau['total']['archives'] >= 1, tableau['total'])

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
