"""Documents contract, real HTTP and SQLite; never opens the production database."""
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

_temp = tempfile.TemporaryDirectory(prefix='bm318d-documents-')
os.environ['MC_DB'] = str(Path(_temp.name) / 'documents.sqlite3')
import MissionControl as mc
import mc_security as security


class Documents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mc.connect() as c:
            c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT)')
            c.execute("INSERT INTO projects VALUES(1,'First'),(2,'Second')")
        mc.init()
        cls.operator = security.operator(mc.TOKEN, mc.TOKEN)
        cls.admin = security.operator(mc.TOKEN, mc.TOKEN, mc.ADMIN_TOKEN, mc.ADMIN_TOKEN)
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), mc.Handler)
        cls.old_port, cls.old_limit = mc.PORT, mc.LIMITE
        mc.PORT, mc.LIMITE = cls.server.server_port, 10000
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(mc.PORT)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        mc.PORT, mc.LIMITE = cls.old_port, cls.old_limit
        _temp.cleanup()

    def setUp(self):
        with mc.connect() as c:
            # Children before parents, without disabling FK protection.
            while c.execute('SELECT 1 FROM mc_documents LIMIT 1').fetchone():
                c.execute('DELETE FROM mc_documents WHERE id NOT IN (SELECT parent_id FROM mc_documents WHERE parent_id IS NOT NULL)')

    def call(self, action='', data=None, headers=None, project=1):
        path = '/api/mc/documents' + ('/' + action if action else '?project=' + str(project))
        request = urllib.request.Request(self.url + path,
            data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
            headers={'Content-Type': 'application/json', **({'X-MC-Token': mc.TOKEN} if headers is None else headers)})
        try:
            with urllib.request.urlopen(request, timeout=5) as result:
                return result.status, json.load(result)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def create(self, **fields):
        status, body = self.call('save', {'project': 1, 'kind': 'file', 'title': 'Note', **fields})
        self.assertEqual(status, 201, body)
        return body['item']

    def test_roundtrip_move_edit_and_reopen_database(self):
        folder = self.create(kind='folder', title='Dossier')
        item = self.create(parent_id=folder['id'], content='Texte libre <script> reste du texte', x=120, y=240)
        status, body = self.call('save', {'project': 1, 'id': item['id'], 'revision': 1, 'x': 301.5, 'parent_id': None})
        self.assertEqual(status, 201, body)
        saved = body['item']
        self.assertEqual((saved['revision'], saved['x'], saved['y'], saved['parent_id']), (2, 301.5, 240, None))
        self.assertEqual(saved['content'], item['content'])
        with mc.connect() as c:
            self.assertEqual(c.execute('SELECT content FROM mc_documents WHERE id=?', (item['id'],)).fetchone()[0], item['content'])
        self.assertEqual(len(self.call()[1]['items']), 2)
        self.assertEqual(self.call(project=2)[1]['items'], [])

    def test_anonymous_http_and_internal_calls_denied(self):
        self.assertEqual(self.call(headers={})[0], 403)
        for action in ('save', 'delete'):
            self.assertEqual(self.call(action, {'project': 1, 'id': 1}, headers={})[0], 403)
            with mc.connect() as c, self.assertRaises(PermissionError):
                mc.dispatch(c, '/api/mc/documents/' + action, {'project': 1, 'id': 1})

    def test_restricted_agent_cannot_access_documents(self):
        with security.use(self.admin), mc.connect() as c:
            agent = mc.dispatch(c, '/api/mc/agent', {'project': 1, 'name': 'Restricted', 'role': 'backend'})['id']
            token = security.issue(1, agent, ['read_context', 'note'])['token']
        headers = {'X-MC-Agent-Token': token}
        self.assertEqual(self.call(headers=headers)[0], 403)
        for action in ('save', 'delete'):
            self.assertEqual(self.call(action, {'project': 1, 'id': 1}, headers=headers)[0], 403)

    def test_cross_project_ids_and_parents_rejected(self):
        folder = self.create(kind='folder')
        item = self.create()
        for action in ('save', 'delete'):
            self.assertEqual(self.call(action, {'project': 2, 'id': item['id'], 'revision': 1})[0], 400)
        self.assertEqual(self.call('save', {'project': 2, 'title': 'Other', 'parent_id': folder['id']})[0], 400)
        self.assertEqual(len(self.call()[1]['items']), 2)

    def test_cycles_nonfolder_parent_and_nonempty_deletion_rejected(self):
        folder = self.create(kind='folder')
        child = self.create(kind='folder', parent_id=folder['id'])
        item = self.create()
        for parent in (folder['id'], child['id'], item['id'], 999999):
            self.assertEqual(self.call('save', {'project': 1, 'id': folder['id'], 'revision': 1, 'parent_id': parent})[0], 400)
        self.assertEqual(self.call('delete', {'project': 1, 'id': folder['id'], 'revision': 1})[0], 400)
        self.assertEqual(self.call('delete', {'project': 1, 'id': child['id'], 'revision': 1})[0], 201)
        self.assertEqual(self.call('delete', {'project': 1, 'id': folder['id'], 'revision': 1})[0], 201)

    def test_revision_prevents_stale_save_and_delete(self):
        item = self.create()
        data = {'project': 1, 'id': item['id'], 'revision': 1, 'content': 'new'}
        self.assertEqual(self.call('save', data)[0], 201)
        self.assertEqual(self.call('save', {**data, 'content': 'lost update'})[0], 409)
        self.assertEqual(self.call('delete', data)[0], 409)
        self.assertEqual(self.call('save', {'project': 1, 'id': item['id'], 'title': 'no version'})[0], 400)
        self.assertEqual(self.call()[1]['items'][0]['content'], 'new')

    def test_invalid_values_and_unknown_ids_do_not_write(self):
        for fields in ({'title': ''}, {'title': 'x' * 161}, {'content': 'x' * 8001}, {'kind': 'command'},
                       {'x': -1}, {'x': 10001}, {'x': float('nan')}, {'y': True}, {'y': '4'},
                       {'parent_id': True}, {'id': 999999, 'revision': 1}, {'id': 1.5, 'revision': 1},
                       {'project': 999}, {'content': {}}, {'kind': 'folder', 'content': 'invalid'}):
            with self.subTest(fields=str(fields)[:100]):
                self.assertEqual(self.call('save', {'project': 1, 'title': 'Valid', **fields})[0], 400)
        self.assertEqual(self.call()[1]['items'], [])

    def test_migration_is_additive_and_idempotent(self):
        item = self.create(content='preserved')
        mc.init()
        self.assertEqual(self.call()[1]['items'][0], item)
        with mc.connect() as c:
            self.assertEqual([tuple(row) for row in c.execute('SELECT id,name FROM projects ORDER BY id')], [(1, 'First'), (2, 'Second')])


if __name__ == '__main__':
    unittest.main()
