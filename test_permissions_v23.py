"""Verified identity tests through HTTP and direct broker calls, isolated DB."""
import contextlib,json,os,tempfile,threading,time,unittest,urllib.request,urllib.error
from pathlib import Path
_temp=tempfile.TemporaryDirectory(prefix='dioptre-auth-')
os.environ['MC_DB']=str(Path(_temp.name)/'auth.sqlite3')
import MissionControl as mc
import mc_security as security

class PermissionsV23(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mc.connect() as c:
            c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT)')
            c.execute("INSERT INTO projects VALUES(1,'test'),(2,'other')")
        mc.init()
        cls.admin=security.operator(mc.TOKEN,mc.TOKEN,mc.ADMIN_TOKEN,mc.ADMIN_TOKEN)
        cls.operator=security.operator(mc.TOKEN,mc.TOKEN)
        with security.use(cls.admin),mc.connect() as c:
            cls.a=mc.dispatch(c,'/api/mc/agent',{'project':1,'name':'A','role':'backend','team':'A'})['id']
            cls.b=mc.dispatch(c,'/api/mc/agent',{'project':1,'name':'B','role':'manager','team':'B'})['id']
            cls.job_a=mc.job_creer(c,1,{'agent_id':cls.a,'title':'A','task':'A'})['id']
            cls.job_b=mc.job_creer(c,1,{'agent_id':cls.b,'title':'B','task':'B'})['id']
        cls.server=__import__('http.server',fromlist=['ThreadingHTTPServer']).ThreadingHTTPServer(('127.0.0.1',0),mc.Handler)
        cls.old_port=mc.PORT;mc.PORT=cls.server.server_port
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();mc.PORT=cls.old_port
    def token(self,actions=None,ttl=900):
        with security.use(self.admin):return security.issue(1,self.a,actions or ['read_context','job_create','job_run','job_control'],ttl)
    def http(self,path,payload=None,headers=None):
        headers={'Content-Type':'application/json',**(headers or {})}
        request=urllib.request.Request(self.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=5) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            with e:return e.code,json.load(e)
    def test_01_internal_dispatch_requires_identity(self):
        with mc.connect() as c:
            with self.assertRaises(PermissionError):mc.dispatch(c,'/api/mc/agent',{'project':1,'name':'Forged','role':'manager'})
    def test_02_forged_principal_rejected(self):
        with self.assertRaises(PermissionError):
            with security.use(security.Principal('admin')):pass
    def test_03_operator_cannot_claim_admin_actor(self):
        with security.use(self.operator),mc.connect() as c:
            with self.assertRaises(PermissionError):mc.job_approuver(c,1,self.job_a,{'agent_id':self.b})
    def test_04_agent_identity_is_bound(self):
        principal=security.authenticate_agent(self.token()['token'])
        with security.use(principal),mc.connect() as c:
            with self.assertRaises(PermissionError):mc.dispatch(c,'/api/mc/job',{'project':1,'agent_id':self.b,'title':'Fake','task':'x'})
            with self.assertRaises(PermissionError):mc.dispatch(c,'/api/mc/job',{'project':2,'agent_id':self.a,'title':'Fake','task':'x'})
    def test_05_direct_job_control_cannot_cross_agents(self):
        principal=security.authenticate_agent(self.token()['token'])
        with security.use(principal),mc.connect() as c:
            with self.assertRaises(PermissionError):mc.job_annuler(c,1,self.job_b)
    def test_06_read_scope_and_legacy_denied(self):
        headers={'X-MC-Agent-Token':self.token()['token']}
        self.assertEqual(self.http(f'/api/mc/context?project=1&agent={self.a}',headers=headers)[0],200)
        for path in (f'/api/mc/context?project=1&agent={self.b}',f'/api/mc/job?project=1&id={self.job_b}','/api/state','/api/mc/state?project=1'):
            self.assertEqual(self.http(path,headers=headers)[0],403,path)
    def test_07_agent_cannot_grant_permissions_or_edit_identity(self):
        headers={'X-MC-Agent-Token':self.token()['token']}
        for path,payload in (('permissions',{'team':'A','can_run_tests':True}),('agent/update',{'id':self.a,'team':'B'}),('security/token',{'agent_id':self.b,'actions':['approve']}),('connectors/save',{'name':'fake'})):
            code,_=self.http('/api/mc/'+path,{'project':1,**payload},headers)
            self.assertEqual(code,403,path)
    def test_08_grants_require_admin(self):
        with security.use(self.operator):
            with self.assertRaises(PermissionError):security.issue(1,self.a,['approve'])
        with security.use(self.admin):
            with self.assertRaises(PermissionError):security.issue(1,self.a,['admin'])
    def test_09_revocation_applies_to_existing_principals(self):
        grant=self.token();principal=security.authenticate_agent(grant['token'])
        with security.use(self.admin):security.revoke(grant['grant_id'])
        with self.assertRaises(PermissionError):security.authenticate_agent(grant['token'])
        with self.assertRaises(PermissionError):
            with security.use(principal):pass
    def test_10_expiry(self):
        grant=self.token(ttl=1);time.sleep(1.05)
        with self.assertRaises(PermissionError):security.authenticate_agent(grant['token'])
    def test_11_invalid_agent_header_does_not_fallback_to_human_cookie(self):
        code,_=self.http('/api/mc/state?project=1',headers={'X-MC-Agent-Token':'fake','X-MC-Token':mc.TOKEN})
        self.assertEqual(code,403)
    def test_12_team_permission_checked_again_at_use(self):
        principal=security.authenticate_agent(self.token(['read_context','test'])['token'])
        with security.use(self.admin),mc.connect() as c:c.execute("UPDATE mc_team_permissions SET can_run_tests=0 WHERE project_id=1 AND team='A'")
        try:
            with security.use(principal),mc.connect() as c:
                with self.assertRaises(PermissionError):mc.job_tester(c,1,self.job_a,{'agent_id':self.a,'command':'unittest'})
        finally:
            with mc.connect() as c:c.execute("UPDATE mc_team_permissions SET can_run_tests=1 WHERE project_id=1 AND team='A'")
    def test_13_default_unknown_routes_and_actions_denied(self):
        with security.use(self.admin),mc.connect() as c:
            with self.assertRaises(PermissionError):mc.dispatch(c,'/api/mc/not-registered',{'project':1})
        with security.use(self.operator),mc.connect() as c:
            with self.assertRaises(PermissionError):mc.permissions_definir(c,1,{'team':'A'})
    def test_14_http_admin_grant_roundtrip(self):
        headers={'X-MC-Token':mc.TOKEN,'X-MC-Admin':mc.ADMIN_TOKEN}
        code,data=self.http('/api/mc/security/token',{'project':1,'agent_id':self.a,'actions':['read_context']},headers)
        self.assertEqual(code,201)
        agent_headers={'X-MC-Agent-Token':data['token']}
        self.assertEqual(self.http(f'/api/mc/job?project=1&id={self.job_a}',headers=agent_headers)[0],200)
        code,_=self.http('/api/mc/security/revoke',{'project':1,'grant_id':data['grant_id']},headers)
        self.assertEqual(code,201)
        self.assertEqual(self.http(f'/api/mc/job?project=1&id={self.job_a}',headers=agent_headers)[0],403)
    def test_15_direct_worker_requires_identity(self):
        with self.assertRaises(PermissionError):mc.job_executer(self.job_a,lambda *args:{'files':[]})
    def test_16_legitimate_agent_job_creation(self):
        principal=security.authenticate_agent(self.token()['token'])
        with security.use(principal),mc.connect() as c:
            result=mc.dispatch(c,'/api/mc/job',{'project':1,'agent_id':self.a,'title':'Legitimate','task':'x'})
            self.assertGreater(result['id'],0)

    def test_17_keyword_arguments_cannot_bypass_binding(self):
        principal=security.authenticate_agent(self.token()['token'])
        with security.use(principal),mc.connect() as c:
            with self.assertRaises(PermissionError):mc.job_annuler(c,1,i=self.job_b)
            with self.assertRaises(PermissionError):mc.job_creer(c,1,d={'agent_id':self.b,'title':'Forged','task':'x'})
    def test_18_cannot_supersede_another_agents_note(self):
        with security.use(self.admin),mc.connect() as c:
            note=mc.dispatch(c,'/api/mc/note',{'project':1,'agent_id':self.b,'scope':'agent','content':'Private B'})['id']
        principal=security.authenticate_agent(self.token(['read_context','note'])['token'])
        with security.use(principal),mc.connect() as c:
            with self.assertRaises(PermissionError):
                mc.dispatch(c,'/api/mc/note',{'project':1,'agent_id':self.a,'scope':'agent','supersedes':note,'content':'Override B'})
            self.assertFalse(c.execute('SELECT 1 FROM mc_notes WHERE supersedes=?',(note,)).fetchone())

    def test_19_caller_cannot_choose_expected_authentication_secret(self):
        with self.assertRaises(PermissionError):security.operator('fake','fake','fake','fake')
    def test_20_copied_principal_is_not_a_verified_identity(self):
        import dataclasses
        principal=security.authenticate_agent(self.token()['token'])
        forged=dataclasses.replace(principal,kind='admin')
        with self.assertRaises(PermissionError):
            with security.use(forged):pass

    def test_21_connector_mutations_require_admin_in_http_and_dispatch(self):
        data={'project':1,'kind':'ollama','name':'Local','config':{'url':'http://127.0.0.1:11434'}}
        with security.use(self.operator),mc.connect() as c:
            with self.assertRaises(PermissionError):mc.dispatch(c,'/api/mc/connectors/save',data)
        headers={'X-MC-Token':mc.TOKEN}
        self.assertEqual(self.http('/api/mc/connectors/save',data,headers)[0],403)
        code,response=self.http('/api/mc/connectors/save',data,{**headers,'X-MC-Admin':mc.ADMIN_TOKEN})
        self.assertEqual(code,201,response)
        self.assertEqual(self.http('/api/mc/connectors/list',{'project':1},headers)[0],201)

if __name__=='__main__':unittest.main(verbosity=2)
