"""BM318d V2.3 — tests négatifs des connecteurs (SSRF, erreurs, quotas, coffre, MCP).

Même harnais que test_connectors.py : base temporaire, serveur HTTP local simulé.
Aucune vraie clé, aucun appel à un fournisseur réel.
"""
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import subprocess
import http.server
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
TEMP = tempfile.TemporaryDirectory(prefix='bm318d-v23-')
os.environ['MC_DB'] = str(Path(TEMP.name) / 'test.sqlite3')
import mc_connectors as cx
import mc_credentials as vault

# Ce harnais ne dépend pas de MissionControl : il tourne aussi sous Linux, où
# l'application complète ne peut pas s'importer (bac à sable Windows de Codex).
DB = Path(TEMP.name) / 'test.sqlite3'
BASE = '''
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mc_agents(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, role TEXT, team TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, project_id INTEGER, created TEXT, agent TEXT, status TEXT, message TEXT);
'''


class Connexion(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    c = sqlite3.connect(DB, timeout=20, factory=Connexion)
    c.row_factory = sqlite3.Row
    return c


def initialiser():
    with connect() as c:
        c.executescript(BASE)
        cx.migrate(c)


def creer_agent(project_id, name):
    with connect() as c:
        return c.execute('INSERT INTO mc_agents(project_id,name,role,team) VALUES(?,?,?,?)',
                         (project_id, name, 'backend', 'Général')).lastrowid


class Provider(http.server.BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Provider.requests.append((self.path, {}, dict(self.headers)))
        if self.path.endswith('/api/tags'):
            corps = {'models': [{'name': 'qwen-test:latest'}, {'name': 'llama-test:3b'}]}
        elif self.path.endswith('/models'):
            corps = {'data': [{'id': 'gpt-test'}, {'id': 'gpt-test-mini'}]}
        else:
            self.send_response(404); self.end_headers(); return
        brut = json.dumps(corps).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(brut))); self.end_headers()
        self.wfile.write(brut)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0') or 0)))
        Provider.requests.append((self.path, data, dict(self.headers)))
        if '/slow/' in self.path:
            time.sleep(2)
        if '/fail/' in self.path:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'secret-should-never-be-logged')
            return
        if '/badjson/' in self.path:
            raw = b'pas du json'
        elif '/missing/' in self.path:
            raw = json.dumps({'unexpected': True}).encode()
        elif '/empty/' in self.path:
            raw = json.dumps({'choices': [{'message': {'content': ''}}]}).encode()
        else:
            texte = json.dumps({'summary': 'ok', 'files': [{'path': 'x.txt', 'content': 'ok'}]})
            if '/null/' in self.path:
                raw = b'null'
            else:
                if self.path.endswith('/api/chat'):
                    raw = json.dumps({'message': {'content': texte}}).encode()
                elif self.path.endswith('/chat/completions'):
                    raw = json.dumps({'choices': [{'message': {'content': texte}}]}).encode()
                elif self.path.endswith('/messages'):
                    raw = json.dumps({'content': [{'type': 'text', 'text': texte}]}).encode()
                else:
                    raw = json.dumps({'candidates': [{'content': {'parts': [{'text': texte}]}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Outil:
    def __init__(self, nom='outil', description='d', schema=None):
        self.name = nom
        self.description = description
        self.input_schema = schema if schema is not None else {'type': 'object', 'properties': {}}


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.url = 'http://127.0.0.1:' + str(cls.http.server_port)
        initialiser()
        with connect() as c:
            c.executemany('INSERT OR IGNORE INTO projects VALUES(?,?)', [(1, 'un'), (2, 'deux')])
        cls.agent = creer_agent(1, 'test')
        cls.agent2 = creer_agent(2, 'autre')
        cls.refs = []

    @classmethod
    def tearDownClass(cls):
        for ref in cls.refs:
            try:
                vault.delete(ref)
            except ValueError:
                pass
        cls.http.shutdown()
        cls.http.server_close()

    def call(self, action, **d):
        with connect() as c:
            return cx.dispatch(c, 1, action, d)

    def ref(self, i):
        with connect() as c:
            return cx.row(c, 1, i)['credential_ref']

    def create(self, kind='ollama', **extra):
        config = {'url': self.url, 'model': 'test', 'network_allowed': True, 'timeout': 3, 'max_tokens': 100}
        config.update(extra.pop('config', {}))
        d = {'kind': kind, 'name': 'test', 'enabled': True, 'config': config, **extra}
        i = self.call('save', **d)['id']
        self.refs.append(self.ref(i))
        return i

    # ---------------------------------------------------------------- SSRF ---
    def test_01_ssrf_private_targets_refused(self):
        for url in ('https://10.0.0.5/v1', 'https://192.168.1.10/v1', 'https://172.16.0.1/v1',
                    'https://169.254.169.254/latest/meta-data',
                    'https://0.0.0.0/v1', 'https://224.0.0.1/v1'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self.create(config={'url': url})

    def test_02_ssrf_scheme_and_form(self):
        for url in ('http://example.org/v1', 'https://user:pass@example.org',
                    'https://example.org/v1?k=1', 'https://example.org/v1#x', 'file:///c:/x',
                    'ftp://example.org'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self.create(config={'url': url})

    def test_03_dns_rebinding_resolved_and_refused(self):
        # Un nom public qui résout vers une adresse privée est refusé.
        with mock.patch.object(cx, '_adresses', lambda hote: {__import__('ipaddress').ip_address('10.0.0.7')}):
            with self.assertRaisesRegex(ValueError, 'non publique'):
                self.create(config={'url': 'https://interne.exemple/v1'})
        # La boucle locale reste autorisée : c'est le cas d'Ollama et des tests.
        self.assertEqual(cx.endpoint('http://127.0.0.1:11434'), 'http://127.0.0.1:11434')
        # Et la vérification est refaite juste avant chaque appel (rebinding).
        with mock.patch.object(cx, '_adresses', lambda hote: {__import__('ipaddress').ip_address('192.168.0.9')}):
            with self.assertRaisesRegex(ValueError, 'non publique'):
                cx.verifier_cible('https://interne.exemple/v1')
        self.assertEqual(len(Provider.requests), 0)

    def test_25_rebinding_to_private_between_config_and_request_is_refused(self):
        requests_before=len(Provider.requests)
        public=__import__('ipaddress').ip_address('8.8.8.8')
        private=__import__('ipaddress').ip_address('10.0.0.8')
        url='https://rebind.example/v1'
        with mock.patch.object(cx,'_adresses',side_effect=[{public},{private}]) as resolve, \
             mock.patch.object(cx.socket,'create_connection') as connect:
            cx.validate({'kind':'openai','name':'rebind','config':{'url':url}})
            with self.assertRaisesRegex(ValueError,'non publique'):
                cx.request_json(url,{}, {},1)
            self.assertEqual(resolve.call_count,2)
            connect.assert_not_called()
        self.assertEqual(len(Provider.requests),requests_before)

    def test_26_http_socket_uses_pinned_ip_and_keeps_host_header(self):
        import socket as socket_module
        original=socket_module.create_connection
        observed=[]
        def pinned_connect(address, timeout=None, source_address=None, *args, **kwargs):
            observed.append(address)
            self.assertEqual(address[0],'127.0.0.1')
            cible=('127.0.0.1', address[1])
            try:
                return original(cible, timeout, source_address, *args, **kwargs)
            except TypeError:
                return original(cible, timeout, source_address)
        url='http://localhost:'+str(self.http.server_port)+'/api/tags'
        with mock.patch.object(cx,'_adresses',return_value={__import__('ipaddress').ip_address('127.0.0.1')}), \
             mock.patch.object(cx.socket,'create_connection',side_effect=pinned_connect):
            result=cx.request_get(url,{},3)
        self.assertIn('qwen-test:latest',[item['name'] for item in result['models']])
        self.assertEqual(len(observed),1)
        self.assertEqual(Provider.requests[-1][2]['Host'],'localhost:'+str(self.http.server_port))

    def test_27_https_pins_ip_and_keeps_hostname_verification(self):
        import ssl
        marker=object()
        context=ssl.create_default_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        connection=cx._PinnedHTTPSConnection('api.example.test','203.0.113.8',
                                              port=443,context=context)
        with mock.patch.object(cx.socket,'create_connection',return_value=marker) as connect, \
             mock.patch.object(context,'wrap_socket',return_value=marker) as wrap:
            connection.connect()
        self.assertEqual(connect.call_args.args[0],('203.0.113.8',443))
        self.assertIs(wrap.call_args.args[0],marker)
        self.assertEqual(wrap.call_args.kwargs['server_hostname'],'api.example.test')

    # ------------------------------------------------------------- erreurs ---
    def test_04_http_error_is_typed_and_body_ignored(self):
        i = self.create('openai', config={'url': self.url + '/fail'})
        with self.assertRaisesRegex(ValueError, 'HTTP 500'):
            self.call('test', id=i, approve_network=True)
        with connect() as c:
            appel = c.execute('SELECT status,error FROM mc_connector_calls ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual(appel[0], 'failed')
        self.assertIn('HTTP 500', appel[1])
        self.assertNotIn('secret-should-never-be-logged', json.dumps(self.call('list')))

    def test_05_timeout_is_typed(self):
        i = self.create('openai', config={'url': self.url + '/slow', 'timeout': 1})
        debut = time.time()
        with self.assertRaisesRegex(ValueError, 'Délai dépassé'):
            self.call('test', id=i, approve_network=True)
        self.assertLess(time.time() - debut, 10)

    def test_06_malformed_responses(self):
        for suffixe, motif in (('/badjson', 'JSON invalide'), ('/missing', 'inattendue'), ('/empty', 'vide')):
            with self.subTest(suffixe=suffixe):
                i = self.create('openai', config={'url': self.url + suffixe})
                with self.assertRaisesRegex(ValueError, motif):
                    self.call('test', id=i, approve_network=True)

    def test_07_fallback_reports_each_reason(self):
        mauvais = self.create('openai', config={'url': self.url + '/fail'})
        second = self.create('anthropic', config={'url': self.url + '/fail'})
        self.call('assign', agent_id=self.agent, connector_id=mauvais, priority=0)
        self.call('assign', agent_id=self.agent, connector_id=second, priority=1)
        with connect() as c:
            with self.assertRaisesRegex(ValueError, 'openai.*anthropic'):
                cx.generate(c, 1, self.agent, 'system', 'task')
        self.call('assign', agent_id=self.agent, connector_id=mauvais, remove=True)
        self.call('assign', agent_id=self.agent, connector_id=second, remove=True)

    # --------------------------------------------------------------- quotas ---
    def test_08_quota_is_not_refunded_on_failure(self):
        i = self.create('openai', config={'url': self.url + '/fail'}, calls_limit=2)
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.call('test', id=i, approve_network=True)
        with self.assertRaisesRegex(ValueError, 'Quota'):
            self.call('test', id=i, approve_network=True)
        with connect() as c:
            self.assertEqual(cx.row(c, 1, i)['calls_used'], 2)

    def test_09_interrupted_calls_recovered_on_restart(self):
        with connect() as c:
            c.execute("INSERT INTO mc_connector_calls(project_id,connector_id,operation,status) VALUES(1,1,'chat','running')")
        initialiser()
        with connect() as c:
            ligne = c.execute("SELECT status,error FROM mc_connector_calls ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(ligne[0], 'interrupted')
        self.assertIn('redémarrage', ligne[1])

    # --------------------------------------------------------------- coffre ---
    def test_10_vault_failures_are_reported(self):
        i = self.create('openai')
        with mock.patch.object(vault, 'api', side_effect=ValueError('Coffre Windows indisponible')):
            with self.assertRaisesRegex(ValueError, 'Coffre Windows'):
                vault.put(self.ref(i), 'une-cle')
            with self.assertRaisesRegex(ValueError, 'Coffre Windows'):
                vault.get(self.ref(i))
        # Le connecteur n'a pas changé d'état, et l'erreur ne contient pas la clé.
        with connect() as c:
            self.assertEqual(cx.row(c, 1, i)['state'], 'untested')

    def test_11_empty_secret_refused(self):
        i = self.create('openai')
        for valeur in ('', '   ', None):
            with self.subTest(valeur=valeur):
                with self.assertRaisesRegex(ValueError, 'Clé'):
                    self.call('secret', id=i, secret=valeur)

    @unittest.skipUnless(vault.WINDOWS, 'coffre Windows uniquement')
    def test_12_secret_never_in_state_or_journal(self):
        i = self.create('openai')
        self.call('secret', id=i, secret='cle-tres-secrete-123')
        etat = json.dumps(self.call('list'))
        self.assertNotIn('cle-tres-secrete-123', etat)
        with connect() as c:
            self.assertNotIn('cle-tres-secrete-123', str(list(c.iterdump())))

    # ------------------------------------------------------------------ MCP ---
    def test_13_mcp_tools_limits(self):
        with self.assertRaisesRegex(ValueError, 'nom valide'):
            cx._outil(type('X', (), {'name': '', 'description': '', 'input_schema': {}})())
        with self.assertRaisesRegex(ValueError, 'Schéma'):
            cx._outil(Outil(schema={'type': 'object', 'x': 'a' * 70000}))
        with self.assertRaisesRegex(ValueError, 'Trop d’outils'):
            cx._outils([Outil('o%d' % i) for i in range(cx.MAX_OUTILS + 1)])
        propre = cx._outils([Outil('hello')])
        self.assertEqual(propre[0]['name'], 'hello')

    def test_14_mcp_execution_still_locked(self):
        i = self.create('mcp', config={'url': self.url + '/mcp', 'transport': 'http'})
        with self.assertRaisesRegex(ValueError, 'bloquées'):
            self.call('call', id=i, tool='x', approved=True)
        with connect() as c:
            self.assertEqual(c.execute("SELECT status FROM mc_connector_calls ORDER BY id DESC LIMIT 1").fetchone()[0], 'denied')

    # ------------------------------------------------------- decouverte modeles ---
    def test_19_model_discovery(self):
        ollama = self.create('ollama')
        reponse = self.call('models', id=ollama)
        self.assertIn('qwen-test:latest', reponse['models'])
        ouvert = self.create('openai')
        reponse = self.call('models', id=ouvert)
        self.assertIn('gpt-test', reponse['models'])
        autre = self.create('anthropic')
        with self.assertRaisesRegex(ValueError, 'saisir le nom'):
            self.call('models', id=autre)

    def test_20_last_call_is_visible(self):
        i = self.create('openai')
        self.call('test', id=i, approve_network=True)
        etat = self.call('list')
        connecteur = [x for x in etat['connectors'] if x['id'] == i][0]
        self.assertIsNotNone(connecteur['dernier'])
        self.assertEqual(connecteur['dernier']['status'], 'ok')

    # ------------------------------------------- nouveaux reglages de connecteur ---
    def test_21_models_allowed_refuses_other_model(self):
        i = self.create('openai', config={'models_allowed': ['modele-autorise']})
        with self.assertRaisesRegex(ValueError, 'Modele desactive'):
            self.call('test', id=i, approve_network=True)
        j = self.create('openai', config={'models_allowed': ['test']})
        self.assertTrue(self.call('test', id=j, approve_network=True).get('tested'))

    def test_22_export_import_without_keys(self):
        self.create('openai', config={'models_allowed': []})
        export = self.call('export')
        self.assertEqual(export['version'], 1)
        self.assertTrue(export['connectors'])
        for entree in export['connectors']:
            self.assertNotIn('credential_ref', entree)
            self.assertNotIn('secret', json.dumps(entree))
        avant = len(self.call('list')['connectors'])
        resultat = self.call('import', connectors=export['connectors'])
        self.assertEqual(resultat['importes'], 0)
        self.assertEqual(len(self.call('list')['connectors']), avant)

    def test_23_quota_alert_written_once(self):
        i = self.create('openai', calls_limit=5)
        for _ in range(4):
            self.call('test', id=i, approve_network=True)
        with connect() as c:
            alertes = c.execute("SELECT count(*) FROM events WHERE agent='Connecteurs' AND message LIKE '%80 %'").fetchone()[0]
        self.assertEqual(alertes, 1)
        etat = [x for x in self.call('list')['connectors'] if x['id'] == i][0]
        self.assertTrue(etat['alerte_quota'])

    def test_24_outils_only_for_mcp(self):
        i = self.create('ollama')
        with self.assertRaisesRegex(ValueError, 'MCP'):
            self.call('outils', id=i, approve_network=True)

    # ------------------------------------------------- quota entre processus ---
    def test_17_quota_atomic_across_processes(self):
        i = self.create('ollama', calls_limit=1)
        worker = Path(TEMP.name) / 'worker_quota.py'
        worker.write_text(
            'import os,sys,sqlite3,json\n'
            'sys.path.insert(0, os.environ["MC_ROOT"])\n'
            'import mc_connectors as cx\n'
            'c=sqlite3.connect(os.environ["MC_DB"],timeout=20)\n'
            'c.row_factory=sqlite3.Row\n'
            'r=dict(c.execute("SELECT * FROM mc_connectors WHERE id=?",(int(os.environ["MC_ID"]),)).fetchone())\n'
            'try:\n'
            '    cx.invoke(c,1,r,None,"chat",lambda: {"ok": True})\n'
            '    print("ok")\n'
            'except Exception as e:\n'
            '    print("refus",e)\n',
            encoding='utf-8')
        env = dict(os.environ)
        env.update({'MC_ROOT': str(ROOT), 'MC_DB': str(DB), 'MC_ID': str(i)})
        procs = [subprocess.Popen([sys.executable, str(worker)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding='utf-8', errors='replace')
                 for _ in range(3)]
        sorties = [p.communicate(timeout=60)[0] for p in procs]
        gagnants = [s for s in sorties if s.strip().startswith('ok')]
        self.assertEqual(len(gagnants), 1, sorties)
        with connect() as c:
            self.assertEqual(cx.row(c, 1, i)['calls_used'], 1)

    def test_18_provider_without_key_works_when_vault_unavailable(self):
        i = self.create('openai')
        with mock.patch.object(vault, 'api', side_effect=ValueError('Coffre Windows indisponible')):
            resultat = self.call('test', id=i, approve_network=True)
        self.assertTrue(resultat.get('tested'))
        # À l'inverse, un fournisseur qui exige une clé échoue avec un message clair.
        j = self.create('anthropic')
        with mock.patch.object(vault, 'api', side_effect=ValueError('Coffre Windows indisponible')):
            with self.assertRaisesRegex(ValueError, 'Coffre'):
                self.call('test', id=j, approve_network=True)
        with self.assertRaises(ValueError):
            self.call('test', id=j, approve_network=True)

    # ------------------------------------------------------------- admin (opt-in) ---
    def test_16_admin_control_when_enabled(self):
        jeton = cx._jeton_admin()
        os.environ['MC_CONNECTORS_REQUIRE_ADMIN'] = '1'
        try:
            with self.assertRaisesRegex(ValueError, 'administrateur'):
                self.create()
            with self.assertRaisesRegex(ValueError, 'administrateur'):
                self.call('models', id=1)
            with self.assertRaisesRegex(ValueError, 'administrateur'):
                self.call('save', kind='ollama', name='x', config={'url': self.url}, admin_token='faux')
            if jeton:
                i = self.call('save', kind='ollama', name='admin ok',
                              config={'url': self.url, 'model': 'm', 'network_allowed': True},
                              admin_token=jeton)['id']
                self.assertIsInstance(i, int)
                self.refs.append(self.ref(i))
            else:
                self.skipTest('aucun jeton administrateur sur cette machine')
        finally:
            os.environ.pop('MC_CONNECTORS_REQUIRE_ADMIN', None)
        # Contrôle désactivé par défaut : la sauvegarde repasse.
        self.assertIsInstance(self.create(), int)

    # ---------------------------------------------------------------- projets ---
    def test_15_cross_project_isolation(self):
        i = self.create()
        with connect() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM mc_connector_agents WHERE project_id=2').fetchone())
            with self.assertRaises(ValueError):
                cx.dispatch(c, 2, 'assign', {'agent_id': self.agent, 'connector_id': i})
            with self.assertRaises(ValueError):
                cx.row(c, 2, i)


if __name__ == '__main__':
    unittest.main(verbosity=2)
