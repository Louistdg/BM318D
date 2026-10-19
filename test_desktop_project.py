"""Desktop actions must resolve a real project before sending any mutation."""
import contextlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent


@contextlib.contextmanager
def fixture(state):
    posts = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path == '/':
                body = b'<meta name="mc-token" content="synthetic-session">'
                code = 200
            else:
                code = 500 if state == 'error' else 200
                body = json.dumps(state if isinstance(state, dict) else {}).encode()
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            posts.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true,"file":"synthetic.sqlite3"}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        (folder / 'logs').mkdir()
        (folder / 'logs/admin-token.txt').write_text('synthetic-admin', encoding='utf-8')
        loader = importlib.machinery.SourceFileLoader('desktop_project_fixture', str(ROOT / 'DIOPTRE-Fenetre.pyw'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        window = importlib.util.module_from_spec(spec)
        loader.exec_module(window)
        window.URL = 'http://127.0.0.1:%d/' % server.server_port
        window.LOGS = folder / 'logs'
        shutil.copy2(ROOT / 'DIOPTRE-Stop.py', folder / 'DIOPTRE-Stop.py')
        try:
            yield window, folder, posts, server.server_port
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class DesktopProject(unittest.TestCase):
    def test_unavailable_project_never_sends_window_mutation(self):
        for state in ('error', {'projects': []}, {'projects': [[0, 'invalid']]}, {'projects': [['bad']]}):
            with self.subTest(state=state), fixture(state) as (window, folder, posts, port):
                self.assertFalse(window.tenter_sauvegarde()[0])
                self.assertFalse(window.tenter_arret()[0])
                self.assertEqual(posts, [])

    def test_unavailable_project_never_sends_stop_mutation(self):
        import os
        for state in ('error', {'projects': []}, {'projects': [[0, 'invalid']]}):
            with self.subTest(state=state), fixture(state) as (window, folder, posts, port):
                result = subprocess.run([sys.executable, str(folder / 'DIOPTRE-Stop.py')],
                    env={**os.environ, 'MC_PORT': str(port)}, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(posts, [])
                self.assertNotIn('synthetic-admin', result.stdout + result.stderr)

    def test_window_uses_actual_project(self):
        with fixture({'projects': [[7, 'real']]}) as (window, folder, posts, port):
            self.assertEqual(window.projet_connu(), 7)
            self.assertTrue(window.tenter_sauvegarde()[0])
            self.assertTrue(window.tenter_arret()[0])
            self.assertEqual([body['project'] for _, body in posts], [7, 7])

    def test_stop_uses_actual_project(self):
        import os
        with fixture({'projects': [[7, 'real']]}) as (window, folder, posts, port):
            result = subprocess.run([sys.executable, str(folder / 'DIOPTRE-Stop.py')],
                env={**os.environ, 'MC_PORT': str(port)}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual([body['project'] for _, body in posts], [7])


if __name__ == '__main__':
    unittest.main()
