import tempfile,sqlite3
from pathlib import Path
from test_support_v23 import broker_fixture
import MissionControl as mc
_BROKER_CONTEXT=broker_fixture(mc)
_BROKER_CONTEXT.__enter__()
original=mc.DB
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
 mc.DB=Path(d)/'test.sqlite3'
 with sqlite3.connect(mc.DB) as c:
  c.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT)')
  c.execute("INSERT INTO projects VALUES(1,'Test')")
 mc.init()
 def call(path,**kw):
  with mc.connect() as c:return mc.dispatch(c,path,{'project':1,**kw})
 a=call('/api/mc/agent',name='Gestionnaire',role='manager')['id']
 b=call('/api/mc/agent',name='Architecte 1',role='architect',manager_id=a)['id']
 c=call('/api/mc/agent',name='Architecte 2',role='architect',manager_id=a)['id']
 dev=call('/api/mc/agent',name='Dev',role='backend',manager_id=b)['id']
 with mc.connect() as conn:assert len(mc.snapshot(conn,1)['agents'])==4
 call('/api/mc/agent/update',id=dev,manager_id=c,team='Backend')
 with mc.connect() as conn:
  s=mc.snapshot(conn,1)
  assert len(s['handoffs'])==1 and s['agents'][-1]['manager_id']==c
 try:call('/api/mc/agent/update',id=a,manager_id=dev);raise AssertionError('Cycle accepted')
 except ValueError:pass
 call('/api/mc/link',source_id=b,target_id=c,kind='dependency')
 try:call('/api/mc/link',source_id=c,target_id=b,kind='dependency');raise AssertionError('Link cycle accepted')
 except ValueError:pass
 m=call('/api/mc/mission',title='Application',objective='Construire le backend')['id']
 task=call('/api/mc/assignment',mission_id=m,agent_id=dev,task='Créer API')['id']
 call('/api/mc/assignment/update',id=task,status='done',result='Code proposé',verified=True)
 with mc.connect() as conn:
  assert mc.snapshot(conn,1)['assignments'][0]['verified']==0
 call('/api/mc/assignment/update',id=task,status='reviewed',result='Tests examinés',verified=True)
 call('/api/mc/note',agent_id=dev,scope='agent',content='Contrat API v1')
 with mc.connect() as conn:
  s=mc.snapshot(conn,1)
  assert s['assignments'][0]['verified']==1
  assert len(s['notes'])==1 and len(s['audit'])>=10
 dossier=Path(d)/'fichiers-projet'
 call('/api/mc/settings',key='workspace_dir',value=str(dossier))
 with mc.connect() as conn:
  assert mc.reglages(conn,1)['workspace_dir']==str(dossier.resolve())
  job=mc.job_creer(conn,1,{'agent_id':dev,'title':'Fichier local','task':'Préparer un rapport'})
 assert Path(job['workspace']).is_relative_to(dossier.resolve())
 assert Path(job['workspace']).is_dir()
 try:call('/api/mc/settings',key='workspace_dir',value='chemin-relatif');raise AssertionError('Relative workspace accepted')
 except ValueError:pass
 if mc.os.name=='nt':
  for bad in ('E:\\BM318d-test','C:\\'):
   try:call('/api/mc/settings',key='workspace_dir',value=bad);raise AssertionError('Unsafe drive accepted: '+bad)
   except ValueError:pass
 with mc.connect() as conn:assert mc.reglages(conn,1)['workspace_dir']==str(dossier.resolve())
 print('PASS: agents dynamiques, transfert, passation, cycles, mission, attribution, validation, mémoire, audit')
mc.DB=original
