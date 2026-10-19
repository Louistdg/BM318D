"""DIOPTRE Mission Control: isolated, additive service on 127.0.0.1:31880."""
import http.server,json,sqlite3,shutil,datetime,threading,os,secrets,time,re
from pathlib import Path
import mc_agent
import mc_plan
import mc_connectors
import mc_security
import mc_documents
import mc_legacy
import mc_backups
import mc_missions
import mc_corbeille
import mc_jobs
import mc_agents
import mc_store
from mc_actions import action
import mc_routes
import sys
import contextvars,functools,inspect
ROOT=Path(__file__).resolve().parent
# Base et port surchargeables : les tests d'integration tournent sur une copie
# temporaire, jamais sur la base de travail.

def _base_par_defaut():
    """Base par defaut, avec reprise de l'ancien nom (bm318d.sqlite3)."""
    ancienne = ROOT / 'bm318d.sqlite3'
    nouvelle = ROOT / 'dioptre.sqlite3'
    if not nouvelle.exists() and ancienne.exists():
        try:
            ancienne.rename(nouvelle)
        except OSError:
            return ancienne
    return nouvelle


DB=Path(os.environ.get('MC_DB') or _base_par_defaut())
HOST='127.0.0.1'
PORT=int(os.environ.get('MC_PORT') or 31880)
# Jeton de session : genere a chaque demarrage, injecte dans la page, exige sur
# toutes les routes /api. Il protege des requetes venues d'une page web tierce ;
# il ne protege pas d'un processus local lance par le meme utilisateur.
TOKEN=os.environ.get('MC_TOKEN') or secrets.token_urlsafe(24)
ORIGINES={'http://127.0.0.1:%d'%PORT,'http://localhost:%d'%PORT}
LIMITE=int(os.environ.get('MC_RATE_LIMIT') or 60)  # requetes POST par minute
_fenetres={}
LOCK=threading.RLock()
ROLES=('manager','architect','frontend','backend','database','tester','auditor','security','documentation','specialist')
STATUSES=('idle','working','blocked','done','paused','archived')
class ManagedConnection(sqlite3.Connection):
 def __exit__(self,typ,value,tb):
  try:return super().__exit__(typ,value,tb)
  finally:self.close()
def connect():
 c=sqlite3.connect(DB,timeout=20,factory=ManagedConnection)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 c.execute('PRAGMA busy_timeout=20000')
 return c
def init():
 # Create legacy canvas tables on a clean install, preserving existing rows.
 with connect() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT, priority TEXT, agent TEXT, status TEXT DEFAULT 'todo', created TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, project_id INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP, agent TEXT, status TEXT, message TEXT);
  CREATE TABLE IF NOT EXISTS task_dependencies(task_id INTEGER NOT NULL,depends_on INTEGER NOT NULL,PRIMARY KEY(task_id,depends_on));
  CREATE TABLE IF NOT EXISTS canvas_positions(project_id INTEGER NOT NULL,task_id INTEGER PRIMARY KEY,x INTEGER NOT NULL,y INTEGER NOT NULL);
  """)
  if not c.execute('SELECT 1 FROM projects LIMIT 1').fetchone():c.execute("INSERT INTO projects(name) VALUES('Mon premier projet')")
 # One coherent SQLite backup before the first additive V2.2 migration.
 with connect() as probe:
  needs_v22=not probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mc_connectors'").fetchone()
  needs_documents=not probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mc_documents'").fetchone()
  document_columns={r[1] for r in probe.execute('PRAGMA table_info(mc_documents)')} if not needs_documents else set()
 needs_document_storage=not needs_documents and not {'storage_path','storage_root'}.issubset(document_columns)
 if DB.exists() and (needs_v22 or needs_documents or needs_document_storage):
  prefix='v22-before-' if needs_v22 else 'before-documents-' if needs_documents else 'before-document-storage-'
  sauvegarder(DB.parent/'backups'/(prefix+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
 with connect() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS mc_agents(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   name TEXT NOT NULL,role TEXT NOT NULL,team TEXT NOT NULL DEFAULT 'Général',
   manager_id INTEGER REFERENCES mc_agents(id),status TEXT NOT NULL DEFAULT 'idle',
   model TEXT NOT NULL DEFAULT 'qwen3.5:4b',instructions TEXT NOT NULL DEFAULT '',
   x INTEGER NOT NULL DEFAULT 120,y INTEGER NOT NULL DEFAULT 120,
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_missions(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   title TEXT NOT NULL,objective TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_assignments(
   id INTEGER PRIMARY KEY,mission_id INTEGER NOT NULL REFERENCES mc_missions(id),
   agent_id INTEGER NOT NULL REFERENCES mc_agents(id),
   task TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',
   result TEXT NOT NULL DEFAULT '',verified INTEGER NOT NULL DEFAULT 0,
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_handoffs(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   agent_id INTEGER NOT NULL REFERENCES mc_agents(id),
   old_manager_id INTEGER,new_manager_id INTEGER,
   summary TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_notes(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   agent_id INTEGER REFERENCES mc_agents(id),
   scope TEXT NOT NULL DEFAULT 'project',content TEXT NOT NULL,
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_links(
   project_id INTEGER NOT NULL REFERENCES projects(id),
   source_id INTEGER NOT NULL REFERENCES mc_agents(id),
   target_id INTEGER NOT NULL REFERENCES mc_agents(id),
   kind TEXT NOT NULL CHECK(kind IN ('communication','dependency')),
   PRIMARY KEY(source_id,target_id,kind));
  CREATE TABLE IF NOT EXISTS mc_audit(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL,
   action TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_jobs(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   agent_id INTEGER NOT NULL REFERENCES mc_agents(id),
   mission_id INTEGER,assignment_id INTEGER,
   title TEXT NOT NULL,task TEXT NOT NULL,
   status TEXT NOT NULL DEFAULT 'queued',
   workspace TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',
   proposal TEXT NOT NULL DEFAULT '',diff TEXT NOT NULL DEFAULT '',
   evidence TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '',
   log TEXT NOT NULL DEFAULT '',depends_on INTEGER,
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,started_at TEXT,finished_at TEXT);
  CREATE TABLE IF NOT EXISTS mc_plans(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   mission_id INTEGER,objective TEXT NOT NULL,tasks TEXT NOT NULL DEFAULT '[]',
   assignments TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'proposed',
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_job_deps(
   job_id INTEGER NOT NULL REFERENCES mc_jobs(id),
   depends_on INTEGER NOT NULL REFERENCES mc_jobs(id),
   PRIMARY KEY(job_id,depends_on));
  CREATE TABLE IF NOT EXISTS mc_decisions(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   agent_id INTEGER REFERENCES mc_agents(id),
   title TEXT NOT NULL,decision TEXT NOT NULL,rationale TEXT NOT NULL,
   alternatives TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_messages(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   from_agent INTEGER REFERENCES mc_agents(id),to_agent INTEGER REFERENCES mc_agents(id),
   to_team TEXT,body TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
   read_at TEXT);
  CREATE TABLE IF NOT EXISTS mc_reviews(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   job_id INTEGER NOT NULL REFERENCES mc_jobs(id),
   agent_id INTEGER REFERENCES mc_agents(id),
   kind TEXT NOT NULL,verdict TEXT NOT NULL,findings TEXT NOT NULL DEFAULT '[]',
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_roles(
   project_id INTEGER NOT NULL REFERENCES projects(id),
   key TEXT NOT NULL,label TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
   PRIMARY KEY(project_id,key));
  CREATE TABLE IF NOT EXISTS mc_recruits(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   name TEXT NOT NULL,role TEXT NOT NULL,team TEXT NOT NULL DEFAULT 'Général',
   model TEXT NOT NULL DEFAULT '',justification TEXT NOT NULL,
   status TEXT NOT NULL DEFAULT 'pending',
   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,decided_at TEXT,decided_by INTEGER);
  CREATE TABLE IF NOT EXISTS mc_branches(
   id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),
   name TEXT NOT NULL,architect_id INTEGER REFERENCES mc_agents(id),
   description TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS mc_settings(
   project_id INTEGER NOT NULL REFERENCES projects(id),key TEXT NOT NULL,value TEXT NOT NULL,
   PRIMARY KEY(project_id,key));
  CREATE TABLE IF NOT EXISTS mc_team_permissions(
   project_id INTEGER NOT NULL REFERENCES projects(id),team TEXT NOT NULL,
   can_create_agents INTEGER NOT NULL DEFAULT 1,
   can_approve_jobs INTEGER NOT NULL DEFAULT 1,
   can_run_tests INTEGER NOT NULL DEFAULT 1,
   PRIMARY KEY(project_id,team));
  """)
  # Migration additive : colonnes ajoutees apres coup sur les bases existantes.
  for table,colonne,definition in (
   ('mc_jobs','log',"TEXT NOT NULL DEFAULT ''"),
   ('mc_jobs','depends_on','INTEGER'),
   ('mc_jobs','branch_id','INTEGER'),
   ('mc_agents','skills',"TEXT NOT NULL DEFAULT ''"),
   ('mc_notes','team','TEXT'),
   ('mc_notes','supersedes','INTEGER'),
   ('mc_handoffs','context',"TEXT NOT NULL DEFAULT ''"),
   ('mc_handoffs','ack_at','TEXT'),
   ('mc_handoffs','ack_by','INTEGER'),
   ('mc_assignments','verification',"TEXT NOT NULL DEFAULT 'none'"),
   ('mc_assignments','evidence',"TEXT NOT NULL DEFAULT '{}'"),
   ('mc_assignments','verified_at','TEXT'),
   ('mc_assignments','verified_by','TEXT')):
   existantes={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
   if colonne not in existantes:c.execute('ALTER TABLE '+table+' ADD COLUMN '+colonne+' '+definition)
  c.execute("UPDATE mc_assignments SET verification='human' WHERE verified=1 AND verification='none'")
  # Reprise apres crash : un job reste « running » alors que le processus a disparu.
  c.execute("UPDATE mc_jobs SET status='failed',error='interrompu par un redémarrage du serveur',finished_at=CURRENT_TIMESTAMP WHERE status='running'")
  mc_connectors.migrate(c)
  mc_documents.migrate(c)

def sauvegarder(destination=None, *, inclure_imports=True):
 return mc_backups.sauvegarder(ROOT,DB,destination,inclure_imports=inclure_imports)
def rows(c,q,a=()):
 return [dict(r) for r in c.execute(q,a).fetchall()]
def one(c,q,a=()):
 r=c.execute(q,a).fetchone()
 if not r:raise ValueError('Élément introuvable dans ce projet')
 return dict(r)
def audit(c,p,action,details):
 c.execute('INSERT INTO mc_audit(project_id,action,details) VALUES(?,?,?)',(p,action,json.dumps(details,ensure_ascii=False)[:4000]))
def required_text(d,k,maxlen=500):
 v=str(d.get(k,'')).strip()
 if not v or len(v)>maxlen:raise ValueError('Champ invalide: '+k)
 return v
def project(c,p):
 return one(c,'SELECT id,name FROM projects WHERE id=?',(p,))
def agent(c,p,i):
 return one(c,'SELECT * FROM mc_agents WHERE project_id=? AND id=?',(p,i))
def hierarchy_cycle(c,p,who,manager):
 seen=set()
 while manager is not None:
  if manager==who or manager in seen:raise ValueError('Hiérarchie circulaire refusée')
  seen.add(manager);manager=agent(c,p,manager)['manager_id']
def snapshot(c,p):
 return dict(agents=rows(c,'SELECT * FROM mc_agents WHERE project_id=? ORDER BY id',(p,)),
 missions=rows(c,'SELECT * FROM mc_missions WHERE project_id=? ORDER BY id DESC',(p,)),
 assignments=rows(c,'SELECT a.* FROM mc_assignments a JOIN mc_missions m ON m.id=a.mission_id WHERE m.project_id=? ORDER BY a.id DESC',(p,)),
 handoffs=rows(c,'SELECT * FROM mc_handoffs WHERE project_id=? ORDER BY id DESC LIMIT 60',(p,)),
 notes=rows(c,'SELECT * FROM mc_notes WHERE project_id=? ORDER BY id DESC LIMIT 100',(p,)),
 decisions=rows(c,'SELECT * FROM mc_decisions WHERE project_id=? ORDER BY id DESC LIMIT 50',(p,)),
 messages=rows(c,'SELECT * FROM mc_messages WHERE project_id=? ORDER BY id DESC LIMIT 60',(p,)),
 reviews=rows(c,'SELECT * FROM mc_reviews WHERE project_id=? ORDER BY id DESC LIMIT 60',(p,)),
 roles=roles_projet(c,p),
 recruits=rows(c,'SELECT * FROM mc_recruits WHERE project_id=? ORDER BY id DESC LIMIT 20',(p,)),
 permissions=permissions_lire(c,p),
 links=rows(c,'SELECT * FROM mc_links WHERE project_id=?',(p,)),
 jobs=rows(c,'SELECT id,project_id,agent_id,mission_id,assignment_id,title,task,status,workspace,model,depends_on,branch_id,evidence,error,substr(log,-1500) AS log,created_at,started_at,finished_at FROM mc_jobs WHERE project_id=? ORDER BY id DESC LIMIT 30',(p,)),
 branches=rows(c,'SELECT * FROM mc_branches WHERE project_id=? ORDER BY id',(p,)),
 plans=rows(c,'SELECT id,objective,status,mission_id,created_at FROM mc_plans WHERE project_id=? ORDER BY id DESC LIMIT 10',(p,)),
 audit=rows(c,'SELECT * FROM mc_audit WHERE project_id=? ORDER BY id DESC LIMIT 100',(p,)))
def context_packet(c,p,i):
 a=agent(c,p,i)
 manager=agent(c,p,a['manager_id']) if a['manager_id'] else None
 # Memoire : projet + equipe + agent, sans les notes remplacees par une version plus recente.
 notes=rows(c,"SELECT id,scope,team,content,created_at FROM mc_notes WHERE project_id=? AND (scope='project' OR (scope='team' AND (team=? OR (team IS NULL AND agent_id IN (SELECT id FROM mc_agents WHERE project_id=? AND team=?)))) OR (scope='agent' AND agent_id=?)) AND id NOT IN (SELECT supersedes FROM mc_notes WHERE project_id=? AND supersedes IS NOT NULL) ORDER BY id DESC LIMIT 40",(p,a['team'],p,a['team'],i,p))
 decisions=rows(c,"SELECT title,decision,rationale,alternatives,created_at FROM mc_decisions WHERE project_id=? AND (agent_id IS NULL OR agent_id=?) ORDER BY id DESC LIMIT 20",(p,i))
 messages=rows(c,"SELECT id,from_agent,body,created_at FROM mc_messages WHERE project_id=? AND read_at IS NULL AND (to_agent=? OR to_team=?) ORDER BY id DESC LIMIT 20",(p,i,a['team']))
 assignments=rows(c,"SELECT m.title AS mission,a.task,a.status,a.result,a.verified FROM mc_assignments a JOIN mc_missions m ON m.id=a.mission_id WHERE m.project_id=? AND a.agent_id=? ORDER BY a.id DESC LIMIT 30",(p,i))
 handoffs=rows(c,"SELECT id,summary,created_at,ack_at FROM mc_handoffs WHERE project_id=? AND agent_id=? ORDER BY id DESC LIMIT 10",(p,i))
 colleagues=rows(c,"SELECT id,name,role,team FROM mc_agents WHERE project_id=? AND team=? AND id<>? ORDER BY id",(p,a['team'],i))
 return {'agent':{'id':i,'name':a['name'],'role':a['role'],'team':a['team'],'instructions':a['instructions'],'manager':manager['name'] if manager else None},'notes':notes,'decisions':decisions,'unread_messages':messages,'assignments':assignments,'handoffs':handoffs,'colleagues':colleagues,'warning':'Dossier de contexte préparé automatiquement ; il n’est transmis à un modèle que si un job est lancé explicitement.'}

# --- P1 : jobs d'agent, execution controlee ---------------------------------
ETATS_JOB=('queued','running','paused','proposed','approved','completed','failed','blocked','cancelled')
_annulations=set()
_pauses=set()
_verrous=threading.Lock()

def journal(c,i,ligne):
 """Journal lisible d'un job, borne a 20 000 caracteres."""
 horodatage=datetime.datetime.now().strftime('%H:%M:%S')
 c.execute("UPDATE mc_jobs SET log=substr(log||?,1,20000) WHERE id=?",('['+horodatage+'] '+ligne+'\n',i))

# --- P6 : roles personnalises, recrutement, equipes --------------------------
# --- P7 : application, reglages, recherche, sauvegardes ----------------------
SERVEUR=[None]
VERSION='2.8.4'
MAX_TEXTE=200000
MAX_PREUVE=8000
ADMIN_TOKEN=os.environ.get('MC_ADMIN_TOKEN') or secrets.token_urlsafe(24)
mc_security.configure(TOKEN,ADMIN_TOKEN)
MANIFESTE=ROOT/'installer'/'version.json'
REGLAGES_DEFAUT={'ollama_url':'http://127.0.0.1:11434/api/chat','ollama_model':'qwen3.5:4b',
 'max_jobs':'','auto_backup_minutes':'60','workspace_dir':str(mc_agent.WORKSPACES)}

def sauvegardes_disponibles():
 return mc_backups.disponibles(ROOT)
@action('admin',payload_arg=0)
def restaurer_sauvegarde(c,p,d):
 return mc_backups.restaurer(c,p,d,racine=ROOT,base=DB,audit=audit,init=init)
def demander_arret():
 threading.Thread(target=lambda: SERVEUR[0] and SERVEUR[0].shutdown(),daemon=True).start()
 return {'ok':True,'arret':'imminent'}

def rotation_sauvegardes(limite=10):
 return mc_backups.rotation(ROOT,limite)
def boucle_sauvegardes(minutes):
 return mc_backups.boucle(ROOT,DB,minutes)
def purger_corbeille(c,p,d):
 racines=[reglages(c,p).get('workspace_dir'), str(mc_agent.WORKSPACES)]
 try:jours=int(d.get('jours') or 30)
 except (TypeError,ValueError):raise ValueError('Duree de retention invalide')
 if jours<1 or jours>3650:raise ValueError('Duree de retention hors limites (1 a 3650 jours)')
 try:plafond=int(d.get('taille_max_mo') or 0)
 except (TypeError,ValueError):plafond=0
 resultat=mc_corbeille.purger([r for r in racines if r],jours,plafond,simulation=bool(d.get('simulation')))
 audit(c,p,'corbeille_purgee',resultat)
 return resultat


mc_agents.lier(sys.modules[__name__])
roles_projet=mc_agents.roles_projet
role_valide=mc_agents.role_valide
role_creer=mc_agents.role_creer
permission=mc_agents.permission
permissions_lire=mc_agents.permissions_lire
permissions_definir=mc_agents.permissions_definir
branche_creer=mc_agents.branche_creer
branche_modifier=mc_agents.branche_modifier
acteur=mc_agents.acteur
agent_clone=mc_agents.agent_clone
recrue_creer=mc_agents.recrue_creer
recrue_decider=mc_agents.recrue_decider
agent_archiver=mc_agents.agent_archiver
charge_par_agent=mc_agents.charge_par_agent
plan_proposer=mc_agents.plan_proposer
plan_appliquer=mc_agents.plan_appliquer
orchestrateur_lancer=mc_agents.orchestrateur_lancer
charge_agents=mc_agents.charge_agents
agent_creer=mc_agents.agent_creer
agent_modifier=mc_agents.agent_modifier
mc_store.lier(sys.modules[__name__])
reglages,reglage_definir,rechercher,notifications,historique=mc_store.reglages,mc_store.reglage_definir,mc_store.rechercher,mc_store.notifications,mc_store.historique
mc_jobs.lier(sys.modules[__name__])
job_publie,job_creer,job_lancer,job_pause,job_reprendre,job_en_arriere,job_executer=mc_jobs.job_publie,mc_jobs.job_creer,mc_jobs.job_lancer,mc_jobs.job_pause,mc_jobs.job_reprendre,mc_jobs.job_en_arriere,mc_jobs.job_executer
job_approuver,job_refuser,job_annuler,auteur_preuve,job_tester,review_creer,job_valider,job_commit,rapport_job=mc_jobs.job_approuver,mc_jobs.job_refuser,mc_jobs.job_annuler,mc_jobs.auteur_preuve,mc_jobs.job_tester,mc_jobs.review_creer,mc_jobs.job_valider,mc_jobs.job_commit,mc_jobs.rapport_job
ROUTES=mc_routes.construire(sys.modules[__name__])


def _dispatch(c,path,d):
 mc_security.authorize_route(c,path,d)
 p=int(d.get('project',0))
 if path not in mc_routes.SANS_PROJET:
  project(c,p)
 if path.startswith('/api/mc/connectors/'):
  return mc_connectors.dispatch(c,p,path.rsplit('/',1)[-1],d)
 fonction=ROUTES.get(path)
 if fonction is None:raise ValueError('Action inconnue')
 return fonction(c,p,d)


def dispatch(c,path,d,principal=None):
 identity=principal if principal is not None else mc_security.current()
 with mc_security.use(identity):
  mc_security.authorize_route(c,path,d)
  return _dispatch(c,path,d)

class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def reply(self,data,code=200):
  b=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
  self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
  self.end_headers();self.wfile.write(b)
 # --- securite commune a toutes les routes ---
 def _hote_ok(self):
  return (self.headers.get('Host') or '').strip() in ('127.0.0.1:%d'%PORT,'localhost:%d'%PORT)
 def _origine_ok(self):
  origine=self.headers.get('Origin')
  return (not origine) or origine in ORIGINES
 def _jeton_ok(self):
  fourni=self.headers.get('X-MC-Token') or ''
  if not fourni:
   # Le cookie porte le meme jeton pour les pages historiques qui utilisent
   # fetch sans en-tete supplementaire (SameSite=Strict : pas d'envoi croise).
   for morceau in (self.headers.get('Cookie') or '').split(';'):
    nom,_,valeur=morceau.strip().partition('=')
    if nom=='mc_token':fourni=valeur
  return secrets.compare_digest(fourni,TOKEN)
 def _limite_ok(self):
  with LOCK:
   maintenant=time.monotonic()
   identite=(self.principal.kind,self.principal.agent)
   route=self.path.split('?',1)[0]
   cle=(identite,route)
   debut,compte=_fenetres.get(cle,(maintenant,0))
   if maintenant-debut>=60:debut,compte=maintenant,0
   sensibles=('/api/mc/job/run','/api/mc/backup','/api/mc/restore','/api/mc/shutdown')
   limite=max(3,LIMITE//6) if route in sensibles or route.startswith('/api/mc/connectors/') else LIMITE
   if compte>=limite:return False
   _fenetres[cle]=(debut,compte+1)
   return True
 def _refus(self,code,message):
  b=json.dumps({'error':message},ensure_ascii=False).encode()
  self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
  self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
  if code==429:self.send_header('Retry-After','60')
  self.end_headers();self.wfile.write(b)
 def _api_autorisee(self):
  if not self._hote_ok():self._refus(421,'Hôte non autorisé');return False
  if not self._origine_ok():self._refus(403,'Origine refusée');return False
  try:
   agent_token=self.headers.get('X-MC-Agent-Token')
   if agent_token:
    self.principal=mc_security.authenticate_agent(agent_token)
   else:
    if not self._jeton_ok():self._refus(403,'Jeton de session absent ou invalide');return False
    self.principal=mc_security.operator(TOKEN,TOKEN,self.headers.get('X-MC-Admin') or '',ADMIN_TOKEN)
   if self.command=='GET':
    with mc_security.use(self.principal),connect() as c:mc_security.authorize_read(c,self.path)
  except (PermissionError,ValueError,KeyError) as error:
   self._refus(403,str(error));return False
  return True
 def do_GET(self):
  if not self._hote_ok():return self._refus(421,'Hôte non autorisé')
  if self.path=='/':
   html=(ROOT/'DIOPTRE.html').read_text(encoding='utf-8')
   html=html.replace('</head>','<meta name="mc-token" content="'+TOKEN+'"><link rel="stylesheet" href="/mission.css"><link rel="stylesheet" href="/workspace.css"></head>')
   html=html.replace('</body>','<script src="/mission.js"></script><script src="/security-ui.js"></script><script src="/connectors.js"></script><script src="/workspace.js"></script></body>')
   b=html.encode()
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
   self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
   self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
   self.send_header('Set-Cookie','mc_token='+TOKEN+'; Path=/; HttpOnly; SameSite=Strict')
   self.end_headers();self.wfile.write(b);return
  if self.path in ('/mission.js','/mission.css','/connectors.js','/security-ui.js','/workspace.js','/workspace.css'):
   path=ROOT/self.path[1:];b=path.read_bytes()
   self.send_response(200);self.send_header('Content-Type','text/javascript' if self.path.endswith('.js') else 'text/css')
   self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
   self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(b);return
  if self.path.startswith('/api/'):
   if not self._api_autorisee():return
   if self.path.startswith('/api/mc/documents?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     p=int(parse_qs(urlsplit(self.path).query)['project'][0])
     with connect() as c:project(c,p);self.reply(mc_documents.items(c,p))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path.startswith('/api/mc/documents/file?'):
    from urllib.parse import parse_qs,urlsplit,quote
    try:
     q=parse_qs(urlsplit(self.path).query);p=int(q['project'][0]);i=int(q['id'][0])
     with connect() as c:
      project(c,p);path,name=mc_documents.local_file(c,p,i,reglages(c,p).get('workspace_dir'));body=path.read_bytes()
     self.send_response(200);self.send_header('Content-Type','application/octet-stream')
     self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name,safe=''))
     self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
     self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    except (ValueError,KeyError,OSError) as e:self.reply({'error':str(e)},404)
    return
   if self.path.startswith('/api/mc/context?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     q=parse_qs(urlsplit(self.path).query);p=int(q['project'][0]);i=int(q['agent'][0])
     with connect() as c:project(c,p);result=context_packet(c,p,i)
     self.reply(result)
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path.startswith('/api/mc/state?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     p=int(parse_qs(urlsplit(self.path).query)['project'][0])
     with connect() as c:project(c,p);self.reply(snapshot(c,p))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path.startswith('/api/mc/report?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     q=parse_qs(urlsplit(self.path).query);p=int(q['project'][0]);i=int(q['job'][0])
     with connect() as c:self.reply(rapport_job(c,p,i))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path=='/api/mc/version':
    self.reply({'version':VERSION});return
   if self.path=='/api/mc/update/check':
    propose=None
    try:propose=json.loads(MANIFESTE.read_text(encoding='utf-8')).get('version')
    except (OSError,ValueError):pass
    self.reply({'version':VERSION,'proposee':propose,'a_jour':bool(propose and propose==VERSION)});return
   if self.path=='/api/mc/backups':
    self.reply({'backups':sauvegardes_disponibles()});return
   if self.path.startswith('/api/mc/settings?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     p2=int(parse_qs(urlsplit(self.path).query)['project'][0])
     with connect() as c:project(c,p2);self.reply(reglages(c,p2))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path.startswith('/api/mc/search?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     q=parse_qs(urlsplit(self.path).query);p3=int(q['project'][0])
     with connect() as c:project(c,p3);self.reply(rechercher(c,p3,q.get('q',[''])[0]))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path.startswith('/api/mc/notifications?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     p4=int(parse_qs(urlsplit(self.path).query)['project'][0])
     with connect() as c:project(c,p4);self.reply(notifications(c,p4))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path.startswith('/api/mc/history?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     p5=int(parse_qs(urlsplit(self.path).query)['project'][0])
     with connect() as c:project(c,p5);self.reply(historique(c,p5))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path=='/api/mc/models':
    try:self.reply({'models':mc_agent.modeles_ollama()})
    except Exception as e:self.reply({'models':[],'error':'Ollama indisponible : '+str(e)[:200]},200)
    return
   if self.path.startswith('/api/mc/job?'):
    from urllib.parse import parse_qs,urlsplit
    try:
     q=parse_qs(urlsplit(self.path).query);p=int(q['project'][0]);i=int(q['id'][0])
     with connect() as c:self.reply(job_publie(c,p,i))
    except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
    return
   if self.path=='/api/state':
    with connect() as c:self.reply(mc_legacy.etat(c))
    return
   self._refus(404,'Route inconnue');return
  self._refus(404,'Route inconnue')
 def do_POST(self):
  if not (self.path.startswith('/api/') or self.path=='/event'):return self._refus(404,'Route inconnue')
  # Le corps est lu avant tout refus : sinon la fermeture de la connexion avec
  # des octets non lus fait perdre la reponse au client (RST sous Windows).
  try:n=int(self.headers.get('Content-Length','0'))
  except ValueError:n=0
  limite=2*1024*1024 if self.path=='/api/ollama' else 12*1024*1024 if self.path=='/api/mc/documents/import' else 16000
  if n<0 or n>limite:
   self.close_connection=True;return self._refus(413,'Taille invalide (limite %d octets)'%limite)
  corps=self.rfile.read(n) if n else b''
  if not self._api_autorisee():return
  if not self._limite_ok():return self._refus(429,'Trop de requêtes : patientez une minute')
  if self.path in ('/api/mc/restore','/api/mc/settings','/api/mc/shutdown','/api/mc/corbeille/purge'):
   if not secrets.compare_digest(self.headers.get('X-MC-Admin') or '',ADMIN_TOKEN):
    return self._refus(403,'Jeton administrateur requis')
  if 'application/json' not in (self.headers.get('Content-Type') or '').lower():
   return self._refus(415,'Content-Type application/json requis')
  if not self.path.startswith('/api/mc/'):
   # Anciennes routes (/api/task, /api/event...) : le corps a deja ete lu, on le
   # remet a disposition du gestionnaire historique.
   if self.principal.kind=='agent':return self._refus(403,'Route historique non autorisée aux agents')
   fonction=mc_legacy.ROUTES_POST.get(self.path)
   if fonction is None:return self._refus(404,'Route inconnue')
   try:
    if not corps:raise ValueError('Corps vide')
    d=json.loads(corps)
    if not isinstance(d,dict):raise ValueError('Corps JSON invalide')
    if self.path=='/api/ollama':
     with connect() as c:result=fonction(c,d)
     self.reply(result);return
    with LOCK,connect() as c:result=fonction(c,d)
    self.reply({'ok':True,**result},201);return
   except PermissionError as e:self.reply({'error':str(e)},403);return
   except (ValueError,KeyError,TypeError,sqlite3.Error) as e:self.reply({'error':str(e)},400);return
  try:
   if not corps:raise ValueError('Corps vide')
   d=json.loads(corps)
   if not isinstance(d,dict):raise ValueError('Corps JSON invalide')
   if self.path=='/api/mc/connectors/test':
    with connect() as c:result=dispatch(c,self.path,d,principal=self.principal)
   else:
    with LOCK,connect() as c:result=dispatch(c,self.path,d,principal=self.principal)
   self.reply({'ok':True,**result},201)
  except PermissionError as e:self.reply({'error':str(e)},403)
  except mc_documents.RevisionConflict as e:self.reply({'error':str(e)},409)
  except FileExistsError as e:self.reply({'error':str(e)},409)
  except (ValueError,KeyError,TypeError,sqlite3.Error) as e:self.reply({'error':str(e)},400)
if __name__=='__main__':
 import sys
 if '--demo' in sys.argv:
  import mc_demo
  init()
  with connect() as c:
   resultat=mc_demo.creer(c)
  print('Demonstration creee : projet',resultat.get('project_id'),flush=True)
  sys.exit(0)
 if '--sauvegarde' in sys.argv:
  chemin=sauvegarder()
  print('Sauvegarde écrite : '+str(chemin),flush=True);sys.exit(0)
 init()
 with connect() as c:
  try:reglages_projet=reglages(c,1)
  except ValueError:reglages_projet=dict(REGLAGES_DEFAUT)
 if reglages_projet.get('ollama_url'):mc_agent.OLLAMA=reglages_projet['ollama_url']
 if reglages_projet.get('max_jobs'):os.environ['MC_MAX_JOBS']=reglages_projet['max_jobs']
 try:minutes=max(0,int(reglages_projet.get('auto_backup_minutes') or 0))
 except ValueError:minutes=0
 if minutes>0:threading.Thread(target=boucle_sauvegardes,args=(minutes,),daemon=True).start()
 try:
  log_root=(DB.parent if os.environ.get('MC_DB') else ROOT)/'logs'
  log_root.mkdir(exist_ok=True)
  (log_root/'admin-token.txt').write_text(ADMIN_TOKEN,encoding='utf-8')
 except OSError:pass
 SERVEUR[0]=http.server.ThreadingHTTPServer((HOST,PORT),Handler)
 adresse='http://%s:%d/'%(HOST,PORT)
 print('DIOPTRE Mission Control '+adresse+' (jeton de session actif)',flush=True)
 SERVEUR[0].serve_forever()
