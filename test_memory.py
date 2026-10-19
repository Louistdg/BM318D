"""Tests P4 : mémoire partagée, décisions, messages ciblés, passations acquittées.

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

passes, echecs = 0, 0


def ok(nom, condition, detail=''):
    global passes, echecs
    if condition:
        passes += 1
        print('  ok    ' + nom)
    else:
        echecs += 1
        print('  ECHEC ' + nom + (('  -> ' + str(detail)[:300]) if detail != '' else ''))


dossier = Path(tempfile.mkdtemp(prefix='dioptre-memoire-'))
mc.DB = dossier / 'memoire.sqlite3'
with mc.connect() as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet memoire')")
mc.init()


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


def contexte(agent_id):
    with mc.connect() as c:
        return mc.context_packet(c, 1, agent_id)


back = appel('/api/mc/agent', name='Dev back', role='backend', team='Backend')['id']
front = appel('/api/mc/agent', name='Dev front', role='frontend', team='Frontend')['id']
chef = appel('/api/mc/agent', name='Chef', role='manager', team='Direction')['id']

print('=== mémoire par portée ===')
appel('/api/mc/note', scope='project', content='REGLE-PROJET : tout est en francais')
appel('/api/mc/note', scope='team', team='Backend', content='REGLE-BACKEND : tests obligatoires')
appel('/api/mc/note', scope='agent', agent_id=back, content='NOTE-PERSO : cle API dans le coffre')
ctx_back = json.dumps(contexte(back), ensure_ascii=False)
ctx_front = json.dumps(contexte(front), ensure_ascii=False)
ok('une note de projet est visible par tous', 'REGLE-PROJET' in ctx_back and 'REGLE-PROJET' in ctx_front)
ok('une note d\'equipe n\'est visible que par son equipe', 'REGLE-BACKEND' in ctx_back and 'REGLE-BACKEND' not in ctx_front)
ok('une note personnelle n\'est visible que par son agent', 'NOTE-PERSO' in ctx_back and 'NOTE-PERSO' not in ctx_front)
try:
    appel('/api/mc/note', scope='team', content='sans equipe')
    ok('une note d\'equipe sans equipe est refusee', False)
except ValueError:
    ok('une note d\'equipe sans equipe est refusee', True)

print('\n=== versions du contexte ===')
ancienne = appel('/api/mc/note', scope='project', content='VERSION-1 : le stockage est en JSON')['id']
nouvelle = appel('/api/mc/note', scope='project', content='VERSION-2 : le stockage est en SQLite', supersedes=ancienne)['id']
ctx = json.dumps(contexte(back), ensure_ascii=False)
ok('la nouvelle version remplace l\'ancienne', 'VERSION-2' in ctx and 'VERSION-1' not in ctx)
try:
    appel('/api/mc/note', scope='agent', agent_id=back, content='x', supersedes=nouvelle)
    ok('on ne remplace pas une note d\'une autre portee', False)
except ValueError:
    ok('on ne remplace pas une note d\'une autre portee', True)

print('\n=== décisions et justifications ===')
decision = appel('/api/mc/decision', agent_id=back, title='Choix du stockage',
                 decision='SQLite pour la base locale', rationale='Pas de serveur a maintenir',
                 alternatives='PostgreSQL (trop lourd), JSON (pas de requetes)')['id']
ctx = json.dumps(contexte(back), ensure_ascii=False)
ok('une decision entre dans le contexte', 'Choix du stockage' in ctx and 'Pas de serveur' in ctx)
ok('les alternatives sont conservees', 'PostgreSQL' in ctx, ctx[:200])
try:
    appel('/api/mc/decision', agent_id=back, title='Sans raison', decision='x')
    ok('une decision sans justification est refusee', False)
except ValueError:
    ok('une decision sans justification est refusee', True)

print('\n=== messages ciblés ===')
m1 = appel('/api/mc/message', from_agent=chef, to_agent=back, body='MESSAGE-AGENT : termine le module')['id']
m2 = appel('/api/mc/message', from_agent=chef, to_team='Backend', body='MESSAGE-EQUIPE : revue vendredi')['id']
ctx_back = json.dumps(contexte(back), ensure_ascii=False)
ctx_front = json.dumps(contexte(front), ensure_ascii=False)
ok('un message a un agent arrive chez lui', 'MESSAGE-AGENT' in ctx_back)
ok('un message a une equipe arrive a ses membres', 'MESSAGE-EQUIPE' in ctx_back)
ok('rien de tout cela n\'arrive a l\'autre equipe', 'MESSAGE-AGENT' not in ctx_front and 'MESSAGE-EQUIPE' not in ctx_front)
try:
    appel('/api/mc/message', from_agent=chef, to_agent=back, to_team='Backend', body='ambigu')
    ok('un message a la fois agent et equipe est refuse', False)
except ValueError:
    ok('un message a la fois agent et equipe est refuse', True)
try:
    appel('/api/mc/message', from_agent=chef, body='a personne')
    ok('un message sans destinataire est refuse', False)
except ValueError:
    ok('un message sans destinataire est refuse', True)

print('\n=== accusé de lecture ===')
appel('/api/mc/message/read', id=m1, agent_id=back)
ctx_back = json.dumps(contexte(back), ensure_ascii=False)
ok('un message lu quitte les non-lus', 'MESSAGE-AGENT' not in ctx_back)
ok('l\'autre message reste non lu', 'MESSAGE-EQUIPE' in ctx_back)
reponse = appel('/api/mc/message/read', id=m1, agent_id=back)
ok('relire un message ne casse rien', reponse['deja_lu'] is True, reponse)
try:
    appel('/api/mc/message/read', id=m1, agent_id=front)
    ok('un agent ne lit pas le courrier d\'un autre', False)
except ValueError:
    ok('un agent ne lit pas le courrier d\'un autre', True)

print('\n=== passation et accusé de réception ===')
appel('/api/mc/agent/update', id=back, manager_id=chef)
with mc.connect() as c:
    passation = c.execute('SELECT * FROM mc_handoffs ORDER BY id DESC LIMIT 1').fetchone()
    passation = dict(zip([d[0] for d in c.execute('SELECT * FROM mc_handoffs LIMIT 1').description], passation)) if passation else {}
ok('un changement de responsable cree une passation', bool(passation), passation)
ok('la passation porte un contexte complet', bool(passation.get('context')) and 'agent' in (passation.get('context') or ''), (passation.get('context') or '')[:120])
with mc.connect() as c:
    message = c.execute('SELECT * FROM mc_messages WHERE to_agent=? ORDER BY id DESC LIMIT 1', (chef,)).fetchone()
ok('le nouveau responsable recoit un message cible', message is not None, message)
try:
    appel('/api/mc/handoff/ack', id=passation['id'], agent_id=back)
    ok('seul le nouveau responsable acquitte', False)
except ValueError:
    ok('seul le nouveau responsable acquitte', True)
appel('/api/mc/handoff/ack', id=passation['id'], agent_id=chef)
with mc.connect() as c:
    apres = dict(zip([d[0] for d in c.execute('SELECT * FROM mc_handoffs LIMIT 1').description],
                     c.execute('SELECT * FROM mc_handoffs WHERE id=?', (passation['id'],)).fetchone()))
ok('l\'acquittement est enregistre', bool(apres['ack_at']) and apres['ack_by'] == chef, apres)
try:
    appel('/api/mc/handoff/ack', id=passation['id'], agent_id=chef)
    ok('on n\'acquitte pas deux fois', False)
except ValueError:
    ok('on n\'acquitte pas deux fois', True)

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
