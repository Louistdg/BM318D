"""Documents contract, real HTTP and SQLite; never opens the production database."""
import http.server
import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

_temp = tempfile.TemporaryDirectory(prefix='dioptre-documents-')
os.environ['MC_DB'] = str(Path(_temp.name) / 'documents.sqlite3')
import MissionControl as mc
import mc_security as security
import mc_documents


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

    def test_import_is_copied_to_project_disk_and_served_back(self):
        with security.use(self.admin), mc.connect() as c:
            root=Path(_temp.name)/'local-project-files'
            mc.dispatch(c,'/api/mc/settings',{'project':1,'key':'workspace_dir','value':str(root)})
        folder=self.create(kind='folder',title='Plans')
        data={'project':1,'name':'brief.txt','data':base64.b64encode(b'rapport local').decode(),'parent_id':folder['id']}
        status,body=self.call('import',data)
        self.assertEqual(status,201,body)
        item=body['item'];target=root/'p1'/'fichiers-importes'/('dossier-%d-plans'%folder['id'])/'brief.txt'
        self.assertEqual(target.read_bytes(),b'rapport local')
        self.assertEqual(item['content'],'')
        self.assertEqual(item['storage_path'],target.relative_to(root).as_posix())
        self.assertEqual(item['storage_root'],str(root.resolve()))
        self.assertEqual(body['saved_to'],str(target))
        req=urllib.request.Request(self.url+'/api/mc/documents/file?project=1&id='+str(item['id']),headers={'X-MC-Token':mc.TOKEN})
        with urllib.request.urlopen(req,timeout=5) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(response.read(),b'rapport local')
        with security.use(self.admin),mc.connect() as c:
            mc.dispatch(c,'/api/mc/settings',{'project':1,'key':'workspace_dir','value':str(Path(_temp.name)/'new-project-root')})
            old=mc_documents.items(c,1)['items']
        self.assertEqual(next(x for x in old if x['id']==item['id'])['local_path'],str(target))
        with urllib.request.urlopen(req,timeout=5) as response:self.assertEqual(response.read(),b'rapport local')
        with mc.connect() as c:
            self.assertEqual(c.execute('SELECT content FROM mc_documents WHERE id=?',(item['id'],)).fetchone()[0],'')

    def test_import_rejects_bad_names_and_oversize(self):
        for name in ('../secret.txt','C:secret.txt','NUL.txt',''):
            self.assertEqual(self.call('import',{'project':1,'name':name,'data':base64.b64encode(b'x').decode()})[0],400)
        too_large='A'*((((8*1024*1024+2)//3)*4))
        self.assertEqual(self.call('import',{'project':1,'name':'big.bin','data':too_large})[0],400)

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

    def test_storage_migration_keeps_existing_rows_and_makes_backup(self):
        original=mc.DB;legacy=Path(_temp.name)/'legacy.sqlite3';mc.DB=legacy
        try:
            with mc.connect() as c:
                c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL)')
                c.execute("INSERT INTO projects VALUES(1,'Legacy')")
                c.execute("""CREATE TABLE mc_documents(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL,
                    parent_id INTEGER,kind TEXT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL DEFAULT '',
                    content_type TEXT NOT NULL DEFAULT 'note',x REAL NOT NULL DEFAULT 100,y REAL NOT NULL DEFAULT 100,
                    revision INTEGER NOT NULL DEFAULT 1,deleted_at TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
                c.execute("INSERT INTO mc_documents(id,project_id,kind,title,content) VALUES(1,1,'file','Legacy note','kept')")
            mc.init()
            with mc.connect() as c:
                row=c.execute('SELECT title,content FROM mc_documents WHERE id=1').fetchone()
                columns={r[1] for r in c.execute('PRAGMA table_info(mc_documents)')}
            self.assertEqual(tuple(row),('Legacy note','kept'))
            self.assertTrue({'storage_path','storage_root'}.issubset(columns))
            self.assertTrue(list((legacy.parent/'backups').glob('*.sqlite3')))
        finally:mc.DB=original


    def test_backup_imports_restores_bytes_and_rejects_conflicts(self):
        root=Path(_temp.name)/'archivage-projet'
        with mc.connect() as c:
            result=mc_documents.import_file(c,1,{'name':'archive.txt',
                'data':base64.b64encode(b'contenu sauvegarde').decode()},root)
        destination=Path(_temp.name)/'archives-test'/'snapshot.sqlite3'
        mc.sauvegarder(destination)
        archive=destination.with_suffix('.imports.zip')
        self.assertTrue(archive.is_file())
        target=root/result['item']['storage_path']
        self.assertEqual(target.read_bytes(),b'contenu sauvegarde')
        target.unlink()
        self.assertEqual(mc_documents.restore_imports(destination,archive),1)
        self.assertEqual(target.read_bytes(),b'contenu sauvegarde')
        self.assertEqual(mc_documents.restore_imports(destination,archive),0)
        target.write_bytes(b'autre contenu local')
        with self.assertRaises(FileExistsError):
            mc_documents.restore_imports(destination,archive)
        self.assertEqual(target.read_bytes(),b'autre contenu local')
        target.unlink()
        with self.assertRaises(FileNotFoundError):
            mc_documents.restore_imports(destination,archive.with_name('introuvable.zip'))


    def test_full_restore_after_import_folder_is_lost(self):
        root=Path(_temp.name)/'lost-imports'
        with mc.connect() as c:
            item=mc_documents.import_file(c,1,{'name':'essentiel.txt',
                'data':base64.b64encode(b'donnees indispensables').decode()},root)['item']
        previous_root=mc.ROOT
        mc.ROOT=Path(_temp.name)
        try:
            backup=mc.sauvegarder()
            target=root/item['storage_path']
            self.assertTrue(backup.with_suffix('.imports.zip').is_file())
            target.unlink()
            with security.use(self.admin),mc.connect() as c:
                result=mc.restaurer_sauvegarde(c,1,{'file':backup.name})
            self.assertEqual(result['fichiers_restaures'],1)
            self.assertEqual(target.read_bytes(),b'donnees indispensables')
        finally:
            mc.ROOT=previous_root

    def test_restore_conflict_returns_http_409_json(self):
        """Non-regression V2.5.2 : un conflit de fichier local repond 409 en JSON, sans ecraser."""
        root = Path(_temp.name) / 'conflit-http'
        with mc.connect() as c:
            item = mc_documents.import_file(c, 1, {'name': 'conflit.txt',
                'data': base64.b64encode(b'version archivee').decode()}, root)['item']
        previous_root = mc.ROOT
        mc.ROOT = Path(_temp.name)
        try:
            backup = mc.sauvegarder(Path(_temp.name) / 'backups' / 'conflit-http.sqlite3')
            target = root / item['storage_path']

            def restaurer():
                request = urllib.request.Request(self.url + '/api/mc/restore',
                    data=json.dumps({'project': 1, 'file': backup.name}).encode(),
                    headers={'Content-Type': 'application/json',
                             'X-MC-Token': mc.TOKEN, 'X-MC-Admin': mc.ADMIN_TOKEN})
                try:
                    with urllib.request.urlopen(request, timeout=10) as result:
                        return result.status, json.load(result)
                except urllib.error.HTTPError as error:
                    with error:
                        return error.code, json.load(error)

            target.unlink()
            status, body = restaurer()
            self.assertEqual(status, 201, body)
            self.assertEqual(target.read_bytes(), b'version archivee')
            target.write_bytes(b'modifie localement')
            status, body = restaurer()
            self.assertEqual(status, 409, body)
            self.assertIn('Fichier local', str(body.get('error', '')))
            self.assertEqual(target.read_bytes(), b'modifie localement')
        finally:
            mc.ROOT = previous_root

    def test_delete_requires_revision_with_clear_message(self):
        item = self.create(kind='file', title='A supprimer')
        with self.assertRaises(ValueError) as contexte:
            with mc.connect() as c:
                mc_documents.delete(c, 1, {'id': item['id']})
        self.assertIn('Revision requise', str(contexte.exception))

    def test_delete_moves_imported_file_to_corbeille(self):
        root = Path(_temp.name) / 'corbeille-projet'
        with mc.connect() as c:
            item = mc_documents.import_file(c, 1, {'name': 'a-supprimer.txt',
                'data': base64.b64encode(b'contenu a archiver').decode()}, root)['item']
            resultat = mc_documents.delete(c, 1, {'id': item['id'], 'revision': item['revision']}, root)
        source = root / item['storage_path']
        self.assertFalse(source.exists(), 'le fichier doit quitter fichiers-importes')
        self.assertTrue(resultat.get('corbeille'))
        rangee = Path(resultat['corbeille'])
        self.assertTrue(rangee.is_file())
        self.assertEqual(rangee.read_bytes(), b'contenu a archiver')
        self.assertEqual(rangee.parent.name, 'corbeille')
        with mc.connect() as c:
            ligne = c.execute('SELECT deleted_at FROM mc_documents WHERE id=?', (item['id'],)).fetchone()
        self.assertTrue(ligne and ligne[0])

    def test_huge_manifest_is_refused_before_reading(self):
        """Audit 2.5.3, constat faible 2 : un manifeste enorme est refuse sans etre decompresse."""
        import zipfile
        bombe = Path(_temp.name) / 'bombe.imports.zip'
        with zipfile.ZipFile(bombe, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json', b'0' * (9 * 1024 * 1024))
        instantane = Path(_temp.name) / 'snap-bombe.sqlite3'
        mc.sauvegarder(instantane, inclure_imports=False)
        with self.assertRaises(ValueError) as contexte:
            mc_documents.restore_imports(instantane, bombe)
        self.assertIn('trop volumineux', str(contexte.exception))

    def test_model_names_are_escaped_in_the_page(self):
        """Audit 2.5.3, constat faible 1 : les noms de modeles passent par escapeHtml."""
        page = (Path(__file__).parent / 'DIOPTRE.html').read_text(encoding='utf-8')
        self.assertIn('escapeHtml(m)', page)
        self.assertNotIn("'<option value=\"'+m+'\">'+m+'</option>'", page)


if __name__ == '__main__':
    unittest.main()
