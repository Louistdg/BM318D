"""Une base déjà peuplée survit à init().

Échoue si les projets ou les missions disparaissent.
Base temporaire uniquement.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

import MissionControl as mc

dossier = Path(tempfile.mkdtemp(prefix='dioptre-projets-'))
mc.DB = dossier / 'projets.sqlite3'
mc.ROOT = dossier
with sqlite3.connect(mc.DB) as c:
    c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
    c.execute("INSERT INTO projects(id, name) VALUES(1, 'Existant')")
mc.init()
with mc.connect() as c:
    c.execute("INSERT INTO mc_missions(project_id, title, objective) VALUES(1, 'Mission gardée', 'objectif')")
mc.init()
with mc.connect() as c:
    projet = c.execute('SELECT name FROM projects WHERE id=1').fetchone()
    mission = c.execute('SELECT title FROM mc_missions').fetchone()
ok = projet is not None and projet[0] == 'Existant' and mission is not None and mission[0] == 'Mission gardée'
print('  ok    projets et missions conservés' if ok else '  ECHEC projets ou missions perdus', projet, mission)
sys.exit(0 if ok else 1)
