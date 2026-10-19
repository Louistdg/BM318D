"""Mode demonstration : projet complet, job reellement execute, preuve verifiable."""
import os
import py_compile
import tempfile
import unittest
from pathlib import Path

_temp = tempfile.TemporaryDirectory(prefix='dioptre-demo-')
os.environ['MC_DB'] = str(Path(_temp.name) / 'demo.sqlite3')
os.environ['MC_WORKSPACES'] = str(Path(_temp.name) / 'workspaces')
import MissionControl as mc
import mc_demo


class Demonstration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mc.init()

    def test_creation_complete_et_preuve_reelle(self):
        with mc.connect() as c:
            resultat = mc_demo.creer(c, nom_projet='Test démo')
        self.assertTrue(resultat['cree'])
        self.assertEqual(len(resultat['agents']), 3)
        with mc.connect() as c:
            projet = resultat['project_id']
            self.assertEqual(c.execute('SELECT count(*) FROM mc_agents WHERE project_id=?', (projet,)).fetchone()[0], 3)
            self.assertEqual(c.execute('SELECT count(*) FROM mc_missions WHERE project_id=?', (projet,)).fetchone()[0], 1)
            job = c.execute('SELECT status,evidence,diff,proposal FROM mc_jobs WHERE id=?', (resultat['job'],)).fetchone()
            self.assertEqual(job[0], 'approved')
            import json
            preuve = json.loads(job[1])
            self.assertEqual(preuve['exit_code'], 0)
            self.assertIn('py_compile', preuve['command'])
            self.assertIn('export_csv.py', job[2])
            self.assertEqual(json.loads(job[3])['summary'], mc_demo.TACHE[1])
            affectation = c.execute('SELECT status,verified,verification FROM mc_assignments WHERE id=?',
                                    (resultat['assignment'],)).fetchone()
            self.assertEqual(tuple(affectation), ('done', 1, 'test'))
            revue = c.execute('SELECT verdict FROM mc_reviews WHERE id=?', (resultat['review'],)).fetchone()
            self.assertEqual(revue[0], 'ok')
            note = c.execute('SELECT scope,content FROM mc_notes WHERE id=?', (resultat['note'],)).fetchone()
            self.assertTrue(note[1])
        # la preuve est verifiable : le fichier compile encore
        fichier = Path(resultat['workspace']) / 'export_csv.py'
        self.assertTrue(fichier.is_file())
        py_compile.compile(str(fichier), doraise=True)

    def test_pas_de_doublon(self):
        with mc.connect() as c:
            premier = mc_demo.creer(c, nom_projet='Test doublon')
        with mc.connect() as c:
            second = mc_demo.creer(c, nom_projet='Test doublon')
        self.assertFalse(second['cree'])
        self.assertEqual(premier['project_id'], second['project_id'])

    def test_force_recree_sans_doublon(self):
        with mc.connect() as c:
            premier = mc_demo.creer(c, nom_projet='Test force')
        with mc.connect() as c:
            second = mc_demo.creer(c, nom_projet='Test force', forcer=True)
        self.assertTrue(second['cree'])
        with mc.connect() as c:
            restants = c.execute('SELECT count(*) FROM projects WHERE name=?', ('Test force',)).fetchone()[0]
            agents = c.execute('SELECT count(*) FROM mc_agents WHERE project_id=?', (second['project_id'],)).fetchone()[0]
            jobs = c.execute('SELECT count(*) FROM mc_jobs WHERE project_id=?', (second['project_id'],)).fetchone()[0]
            revues = c.execute('SELECT count(*) FROM mc_reviews WHERE project_id=?', (second['project_id'],)).fetchone()[0]
        self.assertEqual(restants, 1)
        self.assertEqual((agents, jobs, revues), (3, 1, 1), 'la recreation ne doit pas empiler les lignes')


if __name__ == '__main__':
    unittest.main()
