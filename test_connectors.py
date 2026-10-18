"""V2.2 integration: temporary databases, HTTP providers, Windows vault, SDK MCP."""
import os,sys,tempfile,sqlite3,json,threading,http.server,unittest,subprocess,socket,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
TEMP=tempfile.TemporaryDirectory(prefix='bm318d-v22-')
os.environ['MC_DB']=str(Path(TEMP.name)/'test.sqlite3')
# Harnais complet volontairement Windows-only (coffre Credential Manager, bac à sable
# Windows, serveur HTTP local). Sous Linux, test_connectors_securite.py couvre les
# contrôles autonomes. On sort en 3 « NON EXÉCUTÉ », jamais en succès.
if sys.platform != 'win32':
    print('NON EXÉCUTÉ (code 3) : test_connectors.py est Windows-only '
          '(coffre Windows et bac à sable Windows).')
    print('Résumé : 0 test exécuté, 0 échec — statut NON EXÉCUTÉ.')
    sys.exit(3)
import MissionControl as mc
# Apres fusion, MissionControl exige une identite verifiee pour les appels internes
# (mc_security.broker_fixture). Sur ma branche seule, ce module n'existe pas encore.
try:
    from test_support_v23 import broker_fixture
except ImportError:
    broker_fixture = None
if broker_fixture is not None:
    _BROKER = broker_fixture(mc)
    _BROKER.__enter__()
import mc_connectors as cx
import mc_credentials as vault

class Provider(http.server.BaseHTTPRequestHandler):
    requests=[]
    def log_message(self,*args): pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append((self.path,data,dict(self.headers)))
        if '/fail/' in self.path:
            self.send_response(500); self.end_headers();self.wfile.write(b'secret-should-never-be-logged');return
        text=json.dumps({'summary':'test','files':[{'path':'x.txt','content':'ok'}]})
        if '/null/' in self.path: text='null'
        if self.path.endswith('/api/chat'): result={'message':{'content':text}}
        elif self.path.endswith('/chat/completions'): result={'choices':[{'message':{'content':text}}]}
        elif self.path.endswith('/messages'): result={'content':[{'type':'text','text':text}]}
        else: result={'candidates':[{'content':{'parts':[{'text':text}]}}]}
        raw=json.dumps(result).encode(); self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
        cls.url='http://127.0.0.1:'+str(cls.http.server_port)
        with mc.connect() as c:
            c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT)')
            c.executemany('INSERT INTO projects VALUES(?,?)',[(1,'one'),(2,'two')])
        mc.init()
        with mc.connect() as c:
            cls.a=mc.dispatch(c,'/api/mc/agent',{'project':1,'name':'test','role':'backend'})['id']
        cls.ids=[]
    @classmethod
    def tearDownClass(cls):
        for ref in cls.ids: vault.delete(ref)
        cls.http.shutdown();cls.http.server_close()
    def call(self,action,**d):
        with mc.connect() as c:return cx.dispatch(c,1,action,d)
    def ref(self,i):
        with mc.connect() as c:return cx.row(c,1,i)['credential_ref']
    def create(self,kind='ollama',**extra):
        d={'kind':kind,'name':'test','enabled':True,'config':{'url':self.url,'model':'test-model','network_allowed':True,'timeout':3,'max_tokens':100},**extra}
        i=self.call('save',**d)['id'];self.ids.append(self.ref(i));return i
    def test_01_backup_migration(self):
        backups=list((Path(TEMP.name)/'backups').glob('v22-before-*.sqlite3'))
        self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as c:
            self.assertEqual(c.execute('pragma integrity_check').fetchone()[0],'ok')
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='mc_connectors'").fetchone())
        mc.init()
        self.assertEqual(len(list((Path(TEMP.name)/'backups').glob('*.sqlite3'))),1)
    def test_02_providers_and_vault(self):
        for kind in ('ollama','openai','anthropic','gemini'):
            with self.subTest(kind=kind):
                i=self.create(kind)
                self.call('secret',id=i,secret='bm318d-test-secret')
                self.assertEqual(vault.get(self.ref(i)),'bm318d-test-secret')
                self.call('test',id=i,approve_network=True)
                path,body,headers=Provider.requests[-1]
                self.assertNotIn('bm318d-test-secret',json.dumps(body))
                self.assertIn('test-model',json.dumps(body) if kind!='gemini' else path)
        with mc.connect() as c:
            self.assertNotIn('bm318d-test-secret',str(list(c.iterdump())))
        self.assertNotIn('bm318d-test-secret',json.dumps(self.call('list')))
    def test_03_permissions_and_quota(self):
        i=self.create(calls_limit=1)
        with self.assertRaises(ValueError):self.call('test',id=i)
        self.call('test',id=i,approve_network=True)
        with self.assertRaisesRegex(ValueError,'Quota'):self.call('test',id=i,approve_network=True)
        with mc.connect() as c:
            self.assertEqual(cx.row(c,1,i)['calls_used'],1)
            with self.assertRaises(ValueError):cx.row(c,2,i)
        self.call('toggle',id=i,enabled=False)
        with self.assertRaises(ValueError):self.call('test',id=i,approve_network=True)
    def test_04_fallback_and_agent_scope(self):
        bad=self.create(config={'url':self.url+'/fail','model':'bad','network_allowed':True})
        good=self.create('openai')
        self.call('assign',agent_id=self.a,connector_id=bad,priority=0)
        self.call('assign',agent_id=self.a,connector_id=good,priority=1)
        with mc.connect() as c:
            result=cx.generate(c,1,self.a,'system','task')
            self.assertEqual(result['files'][0]['content'],'ok')
            self.assertIsNone(cx.generate(c,2,self.a,'system','task'))
        self.assertNotIn('secret-should-never-be-logged',json.dumps(self.call('list')))
        self.call('assign',agent_id=self.a,connector_id=bad,remove=True)
        self.call('assign',agent_id=self.a,connector_id=good,remove=True)
    def test_05_tools_locked(self):
        i=self.create('mcp')
        self.call('assign',agent_id=self.a,connector_id=i,tools=['read'])
        before=len(Provider.requests)
        with self.assertRaisesRegex(ValueError,'bloquées'):self.call('call',id=i,tool='read',approved=True)
        self.assertEqual(before,len(Provider.requests))
        self.assertEqual(self.call('list')['calls'][0]['status'],'denied')
    def test_06_config_rejects_secrets_and_unsafe_urls(self):
        for cfg in ({'url':self.url,'api_key':'x'},{'url':'https://user:secret@example.org'},{'url':'http://example.org'},{'url':'https://example.org?key=secret'}):
            with self.assertRaises(ValueError):self.create(config=cfg)
    def test_07_mcp_official_sdk(self):
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        source=Path(TEMP.name)/'mcp_server.py'
        source.write_text('from mcp.server.mcpserver import MCPServer\ns=MCPServer("test")\n@s.tool()\ndef hello(name: str) -> str:\n return "Hello "+name\ns.run(transport="streamable-http",host="127.0.0.1",port='+str(port)+')\n')
        with open(Path(TEMP.name)/'mcp.log','w') as log:
            process=subprocess.Popen([sys.executable,str(source)],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                ready=False
                for _ in range(100):
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.2):ready=True;break
                    except OSError:time.sleep(.1)
                self.assertTrue(ready)
                i=self.create('mcp',config={'url':f'http://127.0.0.1:{port}/mcp','network_allowed':True,'timeout':10})
                tools=self.call('test',id=i,approve_network=True)['tools']
                self.assertEqual(tools[0]['name'],'hello')
                self.assertIn('name',tools[0]['inputSchema']['properties'])
            finally:process.terminate();process.wait(timeout=10)
    def test_08_delete(self):
        i=self.create();self.call('secret',id=i,secret='delete-me')
        ref=self.ref(i)
        self.call('delete',id=i)
        self.assertEqual(vault.get(ref),'')
        self.assertNotIn(i,[r['id'] for r in self.call('list')['connectors']])

    def test_09_job_uses_assigned_provider(self):
        import mc_agent
        mc_agent.WORKSPACES=Path(TEMP.name)/'workspaces'
        i=self.create('openai')
        self.call('assign',agent_id=self.a,connector_id=i,model='per-agent-model')
        with mc.connect() as c:
            job=mc.job_creer(c,1,{'agent_id':self.a,'title':'Connector job','task':'Produce a file'})['id']
        result=mc.job_executer(job)
        self.assertEqual(result['status'],'proposed')
        with mc.connect() as c:
            j=mc.job_publie(c,1,job)
            self.assertIn('x.txt',j['diff'])
            self.assertFalse((Path(j['workspace'])/'x.txt').exists())
        self.assertEqual(Provider.requests[-1][1]['model'],'per-agent-model')
        self.call('assign',agent_id=self.a,connector_id=i,remove=True)
    def test_10_http_security(self):
        import urllib.request,urllib.error
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),mc.Handler)
        old_port=mc.PORT;mc.PORT=server.server_port
        threading.Thread(target=server.serve_forever,daemon=True).start()
        url='http://127.0.0.1:'+str(server.server_port)
        def request(path,headers=None,body=None):
            req=urllib.request.Request(url+path,data=body,headers=headers or {})
            try:
                with urllib.request.urlopen(req) as r:return r.status,json.loads(r.read())
            except urllib.error.HTTPError as e:
                status=e.code;e.close();return status,{}
        try:
            body=json.dumps({'project':1}).encode()
            self.assertEqual(request('/api/mc/connectors/list',{'Content-Type':'application/json'},body)[0],403)
            code,data=request('/api/mc/connectors/list',{'Content-Type':'application/json','X-MC-Token':mc.TOKEN},body)
            self.assertEqual(code,201);self.assertIn('connectors',data)
            self.assertEqual(request('/event',{'Content-Type':'application/json'},body)[0],403)
            self.assertEqual(request('/',{'Host':'attacker.example'})[0],421)
        finally:server.shutdown();server.server_close();mc.PORT=old_port
    def test_11_concurrent_quota(self):
        from concurrent.futures import ThreadPoolExecutor
        i=self.create(calls_limit=1)
        def attempt(_):
            try:self.call('test',id=i,approve_network=True);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(attempt,range(5)))
        self.assertEqual(sum(results),1)
        with mc.connect() as c:self.assertEqual(cx.row(c,1,i)['calls_used'],1)

    def test_12_null_response_uses_registered_fallback(self):
        bad=self.create('openai',config={'url':self.url+'/null','model':'bad','network_allowed':True})
        good=self.create('openai')
        self.call('assign',agent_id=self.a,connector_id=bad,priority=0)
        self.call('assign',agent_id=self.a,connector_id=good,priority=1)
        with mc.connect() as c:
            result=cx.generate(c,1,self.a,'system','task')
            self.assertEqual(result['files'][0]['content'],'ok')
            self.assertEqual(cx.row(c,1,bad)['state'],'error')
        self.call('assign',agent_id=self.a,connector_id=bad,remove=True)
        self.call('assign',agent_id=self.a,connector_id=good,remove=True)

if __name__=='__main__':unittest.main(verbosity=2)
