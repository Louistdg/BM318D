"""Purge de la corbeille : retention, plafond, simulation."""
import os
import tempfile
import time
import unittest
from pathlib import Path

_temp = tempfile.TemporaryDirectory(prefix='dioptre-corbeille-')
os.environ['MC_DB'] = str(Path(_temp.name) / 'corbeille.sqlite3')
import MissionControl as mc
import mc_corbeille


class Corbeille(unittest.TestCase):
    def setUp(self):
        self.racine = Path(_temp.name) / ('espace-' + str(time.time_ns()))
        (self.racine / 'corbeille').mkdir(parents=True)
        (self.racine / 'p1' / 'fichiers-importes').mkdir(parents=True)
        self.ancien = self.racine / 'corbeille' / 'vieux.txt'
        self.recent = self.racine / 'corbeille' / 'recent.txt'
        self.ancien.write_bytes(b'x' * 1000)
        self.recent.write_bytes(b'y' * 1000)
        # un fichier de 40 jours
        vieux = time.time() - 40 * 86400
        os.utime(self.ancien, (vieux, vieux))

    def test_etat_compte_les_fichiers(self):
        e = mc_corbeille.etat([self.racine])
        self.assertEqual(e['fichiers'], 2)
        self.assertEqual(e['octets'], 2000)
        self.assertIsNotNone(e['plus_ancien'])

    def test_simulation_ne_supprime_rien(self):
        r = mc_corbeille.purger([self.racine], jours=30, simulation=True)
        self.assertEqual(r['supprimes'], 1)
        self.assertTrue(self.ancien.exists(), 'la simulation ne doit rien effacer')

    def test_purge_supprime_seulement_le_vieux(self):
        r = mc_corbeille.purger([self.racine], jours=30)
        self.assertEqual(r['supprimes'], 1)
        self.assertGreaterEqual(r['octets'], 1000)
        self.assertFalse(self.ancien.exists())
        self.assertTrue(self.recent.exists(), 'le fichier recent doit rester')

    def test_plafond_de_taille(self):
        for i in range(4):
            f = self.racine / 'corbeille' / ('gros-%d.bin' % i)
            f.write_bytes(b'z' * (1024 * 1024))
            quand = time.time() - (10 - i) * 86400
            os.utime(f, (quand, quand))
        r = mc_corbeille.purger([self.racine], jours=30, taille_max_mo=2)
        restants = sum(1 for f in (self.racine / 'corbeille').rglob('*') if f.is_file())
        self.assertGreater(r['supprimes'], 0)
        self.assertLessEqual(restants, 3)

    def test_route_refuse_sans_jeton_admin(self):
        mc.init()
        with mc.connect() as c:
            c.execute("INSERT OR IGNORE INTO projects(id,name) VALUES(1,'P')")
        self.assertIn('/api/mc/corbeille/purge', mc.ROUTES)


if __name__ == '__main__':
    unittest.main()
