"""Test de sauvegarde et de restauration, sur une base temporaire.

Verifie qu'une sauvegarde en ligne est coherente, qu'une restauration remet
exactement les donnees d'avant, et que l'application fonctionne apres coup.
La base de travail n'est jamais ouverte en ecriture.
"""
import sqlite3
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


dossier = Path(tempfile.mkdtemp(prefix='bm318d-restauration-'))
mc.DB = dossier / 'travail.sqlite3'
vraie = mc.DB


def preparer(chemin):
    c = sqlite3.connect(chemin)
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id,name) VALUES(1,'Projet test')")
    c.commit()
    c.close()


preparer(vraie)
mc.init()


def appel(path, **kw):
    with mc.connect() as c:
        return mc.dispatch(c, path, {'project': 1, **kw})


manager = appel('/api/mc/agent', name='Chef', role='manager')['id']
dev = appel('/api/mc/agent', name='Dev', role='backend', manager_id=manager)['id']
mission = appel('/api/mc/mission', title='M', objective='O')['id']
appel('/api/mc/assignment', mission_id=mission, agent_id=dev, task='T')
appel('/api/mc/note', scope='project', content='contexte')


def etat(chemin):
    c = sqlite3.connect(chemin)

    def lire(requete, defaut=None):
        try:
            return c.execute(requete).fetchall()
        except sqlite3.OperationalError:
            return defaut

    donnees = {
        'agents': lire('SELECT id,name,role,manager_id,team FROM mc_agents ORDER BY id', []),
        'missions': lire('SELECT id,title,objective FROM mc_missions ORDER BY id', []),
        'assignments': lire('SELECT id,mission_id,agent_id,task,status,verification FROM mc_assignments ORDER BY id', []),
        'notes': lire('SELECT id,scope,content FROM mc_notes ORDER BY id', []),
        'audit': c.execute('SELECT count(*) FROM mc_audit').fetchone()[0],
        'integrite': c.execute('PRAGMA integrity_check').fetchone()[0],
    }
    c.close()
    return donnees


avant = etat(vraie)
ok('la base de depart contient 2 agents et 1 mission', len(avant['agents']) == 2 and len(avant['missions']) == 1)

sauvegarde = mc.sauvegarder(dossier / 'sauvegarde.sqlite3')
ok('la sauvegarde est ecrite', sauvegarde.exists() and sauvegarde.stat().st_size > 0,
   sauvegarde if sauvegarde.exists() else 'absente')
ok('la sauvegarde est integre', etat(sauvegarde)['integrite'] == 'ok', etat(sauvegarde)['integrite'])
ok('la sauvegarde contient les memes donnees', etat(sauvegarde)['agents'] == avant['agents'])

# Degats : on supprime tout, comme apres une mauvaise migration.
with sqlite3.connect(vraie) as c:
    c.execute('DELETE FROM mc_agents')
    c.execute('DROP TABLE mc_notes')
apres_degats = etat(vraie)
ok('les degats sont reels (plus aucun agent)', apres_degats['agents'] == [], len(apres_degats['agents']))

# Restauration : la sauvegarde est recopiee dans la base de travail.
source = sqlite3.connect(sauvegarde)
cible = sqlite3.connect(vraie)
try:
    source.backup(cible)
finally:
    cible.close()
    source.close()
restaure = etat(vraie)
ok('la restauration remet les agents a l\'identique', restaure['agents'] == avant['agents'], restaure['agents'])
ok('la restauration remet les missions', restaure['missions'] == avant['missions'])
ok('la restauration remet les attributions', restaure['assignments'] == avant['assignments'])
ok('la restauration remet les notes', restaure['notes'] == avant['notes'])
ok('la base restauree est integre', restaure['integrite'] == 'ok', restaure['integrite'])
ok('le journal d\'audit est conserve', restaure['audit'] == avant['audit'], (avant['audit'], restaure['audit']))
ok('les colonnes de verification survivent a la restauration',
   any(r[1] == 'verification' for r in sqlite3.connect(vraie).execute('PRAGMA table_info(mc_assignments)')))

# L'application doit encore fonctionner apres restauration.
nouveau = appel('/api/mc/agent', name='Apres restauration', role='tester')['id']
ok('on peut encore creer un agent apres restauration', isinstance(nouveau, int) and nouveau > 0, nouveau)
with mc.connect() as c:
    ok('la base restauree repond aux lectures', len(mc.snapshot(c, 1)['agents']) == 3)

print('\n%d ok, %d echec(s)' % (passes, echecs))
sys.exit(1 if echecs else 0)
