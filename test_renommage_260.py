"""Non-regression du renommage 2.6.0 : base, sauvegardes, coffre de cles."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_temp = tempfile.TemporaryDirectory(prefix='dioptre-rename-')
os.environ['MC_DB'] = str(Path(_temp.name) / 'test.sqlite3')
import MissionControl as mc
import mc_credentials


class Renommage(unittest.TestCase):
    def test_ancienne_base_reprise_au_premier_demarrage(self):
        dossier = Path(_temp.name) / 'bases'
        dossier.mkdir()
        ancienne = dossier / 'bm318d.sqlite3'
        ancienne.write_bytes(b'contenu')
        ancien_root = mc.ROOT
        mc.ROOT = dossier
        try:
            base = mc._base_par_defaut()
            self.assertEqual(base.name, 'dioptre.sqlite3')
            self.assertTrue(base.exists())
            self.assertFalse(ancienne.exists())
            self.assertEqual(base.read_bytes(), b'contenu')
            # idempotent
            self.assertEqual(mc._base_par_defaut(), base)
        finally:
            mc.ROOT = ancien_root

    def test_une_base_existante_n_est_pas_ecrasee(self):
        dossier = Path(_temp.name) / 'bases2'
        dossier.mkdir()
        (dossier / 'dioptre.sqlite3').write_bytes(b'nouvelle')
        (dossier / 'bm318d.sqlite3').write_bytes(b'ancienne')
        ancien_root = mc.ROOT
        mc.ROOT = dossier
        try:
            base = mc._base_par_defaut()
            self.assertEqual(base.read_bytes(), b'nouvelle')
            self.assertTrue((dossier / 'bm318d.sqlite3').exists(), 'ancienne intouchee')
        finally:
            mc.ROOT = ancien_root

    def test_rotation_couvre_les_anciennes_sauvegardes(self):
        dossier = Path(_temp.name) / 'rotation'
        (dossier / 'backups').mkdir(parents=True)
        ancien_root = mc.ROOT
        mc.ROOT = dossier
        try:
            for i in range(4):
                (dossier / 'backups' / ('bm318d-auto-%02d.sqlite3' % i)).write_bytes(b'x')
            for i in range(4):
                (dossier / 'backups' / ('dioptre-auto-%02d.sqlite3' % i)).write_bytes(b'x')
            supprimes = mc.rotation_sauvegardes(limite=4)
            self.assertEqual(supprimes, 4)
            restants = sorted(p.name for p in (dossier / 'backups').glob('*.sqlite3'))
            self.assertEqual(len(restants), 4)
        finally:
            mc.ROOT = ancien_root

    @unittest.skipUnless(mc_credentials.WINDOWS, 'coffre Windows uniquement')
    def test_cle_ancienne_reprise_par_le_coffre(self):
        import uuid
        ident = str(uuid.uuid4())
        ancienne = mc_credentials.ancienne_cible(ident)
        # ecrit directement l ancienne entree, comme le faisait la 2.5.x
        import ctypes
        dll = mc_credentials.api()
        from mc_credentials import Credential
        brut = 'cle-de-test'.encode('utf-16-le')
        blob = (ctypes.c_ubyte * len(brut)).from_buffer_copy(brut)
        cred = Credential(Type=1, TargetName=ancienne, CredentialBlobSize=len(brut),
                          CredentialBlob=blob, Persist=2, UserName='DIOPTRE')
        self.assertTrue(dll.CredWriteW(ctypes.byref(cred), 0), 'ecriture de test impossible')
        try:
            self.assertEqual(mc_credentials.get(ident), 'cle-de-test')
            # la nouvelle entree existe maintenant
            self.assertEqual(mc_credentials._lire(mc_credentials.target(ident)), 'cle-de-test')
            # et l ancienne a disparu
            self.assertIsNone(mc_credentials._lire(ancienne))
        finally:
            dll.CredDeleteW(mc_credentials.target(ident), 1, 0)
            dll.CredDeleteW(ancienne, 1, 0)


if __name__ == '__main__':
    unittest.main()
