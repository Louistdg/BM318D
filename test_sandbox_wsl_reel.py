"""Bac a sable WSL : essai en conditions reelles (Windows -> WSL -> bubblewrap).

Ces tests ne s'executent que si Windows, WSL, bubblewrap et les runtimes
approuves sont disponibles. Sinon ils sont ignores : aucun faux positif.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent


def _wsl_disponible():
    if os.name != 'nt':
        return False
    try:
        # wsl.exe ecrit en UTF-16 : on ne teste que le code de sortie.
        sortie = subprocess.run(['wsl', '-e', 'bash', '-c',
                                 'test -x /usr/bin/bwrap && test -x /usr/bin/python3'],
                                capture_output=True, timeout=60)
        return sortie.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


PRET = _wsl_disponible()


@unittest.skipUnless(PRET, 'WSL + bubblewrap indisponibles')
class BacASableWSL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['MC_SANDBOX_BACKEND'] = 'wsl'
        os.environ['MC_SANDBOX'] = tempfile.mkdtemp(prefix='sandbox-test-')
        import mc_sandbox
        cls.sandbox = mc_sandbox

    def _executer(self, code, delai=20):
        travail = tempfile.mkdtemp(prefix='job-test-')
        Path(travail, 'essai.py').write_text(code, encoding='utf-8')
        return self.sandbox.executer(['/usr/bin/python3', 'essai.py'], travail, delai=delai)

    def test_code_approuve_s_execute(self):
        r = self._executer("print('bonjour depuis le bac a sable')")
        self.assertEqual(r['exit_code'], 0)
        self.assertIn('bonjour', r['stdout'])

    def test_reseau_refuse(self):
        r = self._executer("import socket;socket.create_connection(('1.1.1.1',80),timeout=3)")
        self.assertNotEqual(r['exit_code'], 0)
        self.assertIn('not permitted', (r.get('stderr') or '').lower() + (r.get('stdout') or '').lower())

    def test_fork_refuse(self):
        r = self._executer('import os;os.fork()')
        self.assertNotEqual(r['exit_code'], 0)

    def test_systeme_de_fichiers_hote_absent(self):
        r = self._executer("print(open('/etc/passwd').read()[:20])")
        self.assertNotEqual(r['exit_code'], 0, 'le fichier hote ne doit pas etre lisible')

    def test_ecriture_tmp_non_persistante(self):
        marqueur = 'dioptre-test-%d' % os.getpid()
        r = self._executer("open('/tmp/%s','w').write('x');print('ok')" % marqueur)
        self.assertEqual(r['exit_code'], 0)
        verif = subprocess.run(['wsl', '-e', 'bash', '-c', 'test -e /tmp/%s && echo present || echo absent' % marqueur],
                               capture_output=True, text=True, timeout=30)
        self.assertIn('absent', verif.stdout, '/tmp du bac a sable ne doit pas toucher celui de l hote')

    def test_runtime_non_approuve_refuse(self):
        with self.assertRaises(Exception):
            self.sandbox.executer(['/bin/true'], tempfile.mkdtemp(prefix='job-test-'))

    def test_racine_du_workspace_seule(self):
        """Un chemin hors workspace est refuse avant tout lancement."""
        with self.assertRaises(Exception):
            self.sandbox.executer(['/usr/bin/python3', 'essai.py'], 'C:\\Windows')


if __name__ == '__main__':
    unittest.main()
