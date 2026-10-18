import http.server,json,sqlite3,threading,urllib.request,urllib.parse,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
# MC_DB permet d'isoler les tests sur une base temporaire ; par defaut la base
# de travail reste bm318d.sqlite3.
DB=Path(os.environ.get('MC_DB') or ROOT/'bm318d.sqlite3')
_CACHE_MODELES={'quand':0.0,'liste':[]}

def modeles_installes():
 """Liste des modeles presents dans Ollama, cache 10 secondes."""
 import time as _temps
 if _temps.time()-_CACHE_MODELES['quand']<10:return _CACHE_MODELES['liste']
 liste=[]
 try:
  with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=3) as reponse:
   liste=[m['name'] for m in json.load(reponse).get('models',[])]
 except Exception:
  liste=[]
 _CACHE_MODELES.update(quand=_temps.time(),liste=liste)
 return liste


def contexte_projet(projet):
 """Contexte factuel court, lu en base. Les zeros sont dits explicitement."""
 faits=["Application: BM318d Control Center (gestion de projet, agents IA locaux, securite V2.3)"]
 def ajoute(texte):
  faits.append(texte)
 try:
  ligne=db("SELECT name FROM projects WHERE id=?",(projet,))
  ajoute("Projet: "+str(ligne[0][0])+(" (id "+str(projet)+")" if ligne else ""))
  n=db("SELECT count(*) FROM mc_agents WHERE project_id=?",(projet,))
  ajoute("Agents: "+str(n[0][0]))
  noms=db("SELECT name FROM mc_agents WHERE project_id=? ORDER BY id LIMIT 6",(projet,))
  if noms:ajoute("Noms des agents: "+", ".join(str(r[0]) for r in noms))
  for table,label in (("mc_missions","Missions"),("tasks","Taches"),("mc_connectors","Connecteurs")):
   n=db("SELECT count(*) FROM "+table+" WHERE project_id=?",(projet,))
   ajoute(label+": "+str(n[0][0]))
  jobs=db("SELECT status,count(*) FROM mc_jobs WHERE project_id=? GROUP BY status",(projet,))
  ajoute("Jobs: "+(", ".join(str(r[0])+" "+str(r[1]) for r in jobs) if jobs else "aucun"))
  evenements=db("SELECT agent,status,substr(message,1,120) FROM events WHERE project_id=? ORDER BY id DESC LIMIT 3",(projet,))
  if evenements:ajoute("Derniers evenements: "+" | ".join(str(e[0])+" ("+str(e[1])+"): "+str(e[2]) for e in evenements))
  regle=db("SELECT value FROM mc_settings WHERE project_id=? AND key='ollama_model'",(projet,))
  if regle:ajoute("Modele configure: "+str(regle[0][0]))
  ajoute("Securite: connecteurs proteges par jeton administrateur, execution de code en bac a sable, MCP verrouille")
 except Exception as erreur:
  ajoute("Contexte partiel ("+type(erreur).__name__+")")
 return "\n".join("- "+f for f in faits)

def modele_ollama(projet):
 """Modele Ollama : variable d'environnement, sinon reglage du projet, sinon defaut."""
 nom=os.environ.get('MC_OLLAMA_MODEL') or 'qwen2.5:3b'
 try:
  ligne=db("SELECT value FROM mc_settings WHERE project_id=? AND key='ollama_model'",(projet,))
  if ligne and ligne[0][0]:nom=str(ligne[0][0])
 except Exception:pass
 return nom

def db(q,a=(),write=False):
 with sqlite3.connect(DB,timeout=15) as c:
  c.execute('PRAGMA busy_timeout=15000')
  r=c.execute(q,a)
  return r.lastrowid if write else r.fetchall()
db('CREATE TABLE IF NOT EXISTS task_dependencies(task_id INTEGER NOT NULL,depends_on INTEGER NOT NULL,PRIMARY KEY(task_id,depends_on))',write=True)
db('CREATE TABLE IF NOT EXISTS canvas_positions(project_id INTEGER NOT NULL,task_id INTEGER PRIMARY KEY,x INTEGER NOT NULL,y INTEGER NOT NULL)',write=True)
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def reply(self,data,code=200):
  b=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
 def do_GET(self):
  if self.path=='/':
   b=(ROOT/'BM318d-Railway.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
  if self.path=='/api/state':
   self.reply({'projects':db('SELECT id,name FROM projects ORDER BY id DESC'),'tasks':db('SELECT id,project_id,title,priority,agent,status FROM tasks ORDER BY id'),'events':db('SELECT id,project_id,created,agent,status,message FROM events ORDER BY id DESC LIMIT 300'),'edges':db('SELECT task_id,depends_on FROM task_dependencies'),'positions':db('SELECT project_id,task_id,x,y FROM canvas_positions')});return
  self.send_error(404)
 def do_POST(self):
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n<1 or n>16000:raise ValueError('Invalid size')
   d=json.loads(self.rfile.read(n))
   if self.path=='/api/project':
    name=str(d['name']).strip()[:120]
    if not name:raise ValueError('name')
    result=db('INSERT INTO projects(name) VALUES(?)',(name,),True)
   elif self.path=='/api/task':
    p=int(d['project']);name=str(d['title']).strip()[:300]
    if not name or not db('SELECT 1 FROM projects WHERE id=?',(p,)):raise ValueError('task')
    result=db('INSERT INTO tasks(project_id,title,priority,agent) VALUES(?,?,?,?)',(p,name,str(d.get('priority','Normale'))[:30],str(d.get('agent','IA 1'))[:80]),True)
   elif self.path=='/api/task/update':
    p=int(d['project']);ident=int(d['id'])
    title=str(d['title']).strip()
    if not title or len(title)>300 or not db('SELECT 1 FROM tasks WHERE id=? AND project_id=?',(ident,p)):raise ValueError('Tâche introuvable ou titre invalide')
    result=db('UPDATE tasks SET title=?,priority=?,agent=? WHERE id=? AND project_id=?',(title,str(d['priority'])[:30],str(d['agent'])[:80],ident,p),True)
   elif self.path=='/api/status':
    result=db('UPDATE tasks SET status=? WHERE id=? AND project_id=?',(str(d['status'])[:50],int(d['id']),int(d['project'])),True)
   elif self.path=='/api/position':
    t=int(d['id']);p=int(d['project'])
    if not db('SELECT 1 FROM tasks WHERE id=? AND project_id=?',(t,p)):raise ValueError('task')
    result=db('INSERT INTO canvas_positions(project_id,task_id,x,y) VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET x=excluded.x,y=excluded.y',(p,t,max(-10000,min(10000,int(d['x']))),max(-10000,min(10000,int(d['y'])))),True)
   elif self.path=='/api/link':
    a=int(d['task']);b=int(d['depends_on']);p=int(d['project'])
    valid={r[0] for r in db('SELECT id FROM tasks WHERE project_id=?',(p,))}
    if a==b or a not in valid or b not in valid:raise ValueError('Invalid tasks')
    graph={}
    for x,y in db('SELECT task_id,depends_on FROM task_dependencies'):graph.setdefault(x,[]).append(y)
    todo=[b];seen=set()
    while todo:
     node=todo.pop()
     if node==a:raise ValueError('Circular dependency')
     if node in seen:continue
     seen.add(node);todo.extend(graph.get(node,[]))
    result=db('INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)',(a,b),True)
   elif self.path in ('/api/event','/event'):
    p=int(d.get('project',d.get('project_id',0)));agent=str(d['agent'])[:100];status=str(d['status'])[:40];message=str(d['message']).strip()[:2000]
    if not message or not agent or status not in ('working','blocked','done','idle') or not db('SELECT 1 FROM projects WHERE id=?',(p,)):raise ValueError('Invalid event')
    result=db('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,agent,status,message),True)
   elif self.path=='/api/ollama':
    p=int(d['project']);prompt=str(d['prompt']).strip()[:5000]
    if not prompt or not db('SELECT 1 FROM projects WHERE id=?',(p,)):raise ValueError('Invalid prompt')
    modele_choisi=str(d.get('model') or '').strip()[:80]
    if modele_choisi and modele_choisi not in modeles_installes():raise ValueError('Modele non installe : '+modele_choisi)
    db('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','working','Mission: '+prompt[:1800]),True)
    try:
     payload=json.dumps({'model':modele_choisi or modele_ollama(p),'keep_alive':'30m','stream':False,'messages':[{'role':'system','content':'Assistant de développement en lecture seule. Ne prétends pas avoir modifié des fichiers ni exécuté des tests. '
               'Contexte réel du projet, seul fiable : '+contexte_projet(p)+'. '
               'Si une information demandée n est pas dans ce contexte, dis clairement que tu ne sais pas.'},{'role':'user','content':prompt}],'options':{'num_predict':300}}).encode()
     req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=payload,headers={'Content-Type':'application/json'})
     with urllib.request.urlopen(req,timeout=120) as r:answer=json.load(r).get('message',{}).get('content','').strip()
     if not answer:raise ValueError('Réponse vide')
     db('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','done',('Réponse non vérifiée: '+answer)[:2000]),True)
     self.reply({'ok':True,'answer':answer});return
    except Exception as e:
     db('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',(p,'Ollama','blocked',str(e)[:2000]),True)
     self.reply({'error':str(e)},502);return
   else:self.send_error(404);return
   self.reply({'ok':True,'id':result},201)
  except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:self.reply({'error':str(e)},400)
if __name__=='__main__':
 print('BM318d Railway UI: http://127.0.0.1:31879/',flush=True)
 http.server.ThreadingHTTPServer(('127.0.0.1',31879),Handler).serve_forever()
