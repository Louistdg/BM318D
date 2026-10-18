"""BM318d Mission Control: isolated, additive service on 127.0.0.1:31880."""
import http.server,importlib.util,json,sqlite3,shutil,datetime,threading,os,secrets,time,re
from pathlib import Path
import mc_agent
import mc_plan
import mc_connectors
import mc_security
import contextvars,functools,inspect
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('legacy',ROOT/'BM318d-WebServer.py')
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
# Base et port surchargeables : les tests d'integration tournent sur une copie
# temporaire, jamais sur la base de travail.
DB=Path(os.environ.get('MC_DB') or ROOT/'bm318d.sqlite3')
HOST='127.0.0.1'
PORT=int(os.environ.get('MC_PORT') or 31880)
# Jeton de session : genere a chaque demarrage, injecte dans la page, exige sur
# toutes les routes /api. Il protege des requetes venues d'une page web tierce ;
# il ne protege pas d'un processus local lance par le meme utilisateur.
TOKEN=os.environ.get('MC_TOKEN') or secrets.token_urlsafe(24)
ORIGINES={'http://127.0.0.1:%d'%PORT,'http://localhost:%d'%PORT}
LIMITE=int(os.environ.get('MC_RATE_LIMIT') or 60)  # requetes POST par minute
_fenetre=[0.0,0]
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
 # One coherent SQLite backup before the first additive V2.2 migration.
 with connect() as probe:
  needs_v22=not probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mc_connectors'").fetchone()
 if needs_v22 and DB.exists():
  sauvegarder(DB.parent/'backups'/('v22-before-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
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

def sauvegarder(destination=None):
 # Copie en ligne (API backup de SQLite) : coherente meme si le serveur ecrit.
 destination=Path(destination) if destination else ROOT/'backups'/('bm318d-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
 destination.parent.mkdir(parents=True,exist_ok=True)
 source=sqlite3.connect(DB,timeout=20);cible=sqlite3.connect(destination)
 try:source.backup(cible)
 finally:cible.close();source.close()
 return destination
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

def job_publie(c,p,i):
 return one(c,'SELECT * FROM mc_jobs WHERE project_id=? AND id=?',(p,i))

def job_creer(c,p,d):
 a=agent(c,p,int(d['agent_id']))
 titre=required_text(d,'title',160);tache=required_text(d,'task',5000)
 mission=d.get('mission_id');mission=int(mission) if mission not in ('',None) else None
 if mission is not None:one(c,'SELECT * FROM mc_missions WHERE project_id=? AND id=?',(p,mission))
 attribution=d.get('assignment_id');attribution=int(attribution) if attribution not in ('',None) else None
 if attribution is not None:
  ligne=one(c,'SELECT a.*,m.project_id AS projet FROM mc_assignments a JOIN mc_missions m ON m.id=a.mission_id WHERE a.id=? AND m.project_id=?',(attribution,p))
  if ligne['agent_id']!=a['id']:
   raise ValueError('L’attribution %d ne concerne pas cet agent'%attribution)
  if mission is not None and ligne['mission_id']!=mission:
   raise ValueError('L’attribution %d n’appartient pas à la mission %d'%(attribution,mission))
 depend=d.get('depends_on');depend=int(depend) if depend not in ('',None) else None
 branche=d.get('branch_id');branche=int(branche) if branche not in ('',None) else None
 if branche is not None:one(c,'SELECT * FROM mc_branches WHERE project_id=? AND id=?',(p,branche))
 if depend is not None:job_publie(c,p,depend)
 modele=str(d.get('model') or a['model']).strip()[:80] or a['model']
 cur=c.execute('INSERT INTO mc_jobs(project_id,agent_id,mission_id,assignment_id,title,task,model,depends_on,branch_id) VALUES(?,?,?,?,?,?,?,?,?)',(p,a['id'],mission,attribution,titre,tache,modele,depend,branche))
 job=cur.lastrowid
 racine=mc_agent.racine_workspace(p,a['id'],job)
 c.execute('UPDATE mc_jobs SET workspace=? WHERE id=?',(str(racine),job))
 journal(c,job,'créé · agent %s · modèle %s'%(a['name'],modele))
 audit(c,p,'job_created',{'id':job,'agent':a['id'],'title':titre})
 return {'id':job,'workspace':str(racine),'model':modele}

def job_lancer(c,p,i):
 j=job_publie(c,p,i)
 if j['status'] not in ('queued','failed','cancelled','blocked'):raise ValueError('Ce job ne peut pas être relancé ('+j['status']+')')
 if j['depends_on'] or rows(c,'SELECT 1 FROM mc_job_deps WHERE job_id=?',(i,)):
  dependances=[r['depends_on'] for r in rows(c,'SELECT depends_on FROM mc_job_deps WHERE job_id=?',(i,))]
  if j['depends_on'] and j['depends_on'] not in dependances:dependances.append(j['depends_on'])
  for dep_id in dependances:
   try:dependance=job_publie(c,p,dep_id)
   except ValueError:dependance=None
   if not dependance or dependance['status'] not in ('approved','completed'):
    c.execute("UPDATE mc_jobs SET status='blocked',error=? WHERE id=?",('Dépendance non approuvée (job %s : %s)'%(dep_id,dependance['status'] if dependance else 'introuvable'),i))
    journal(c,i,'bloqué : dépendance %s non approuvée'%dep_id)
    audit(c,p,'job_blocked',{'id':i,'depends_on':dep_id})
    return {'bloque':True,'id':i}
 with _verrous:_annulations.discard(i);_pauses.discard(i)
 c.execute("UPDATE mc_jobs SET status='queued',error='',finished_at=NULL WHERE id=?",(i,))
 journal(c,i,'en file')
 audit(c,p,'job_queued',{'id':i})
 threading.Thread(target=contextvars.copy_context().run,args=(job_en_arriere,i),daemon=True).start()
 return {'ok':True,'id':i}

def job_pause(c,p,i):
 j=job_publie(c,p,i)
 if j['status']=='proposed':
  c.execute("UPDATE mc_jobs SET status='paused' WHERE id=?",(i,))
  journal(c,i,'en pause (proposition en attente)')
  audit(c,p,'job_paused',{'id':i})
  return {'paused':True}
 if j['status']=='running':
  with _verrous:_pauses.add(i)
  journal(c,i,'pause demandée : appliquée à la fin de l’étape en cours')
  audit(c,p,'job_pause_demandee',{'id':i})
  return {'paused':False,'demandee':True}
 raise ValueError('Ce job ne peut pas être mis en pause ('+j['status']+')')

def job_reprendre(c,p,i):
 j=job_publie(c,p,i)
 if j['status']!='paused':raise ValueError('Ce job n’est pas en pause ('+j['status']+')')
 _pauses.discard(i)
 if (j['proposal'] or '').strip():
  c.execute("UPDATE mc_jobs SET status='proposed' WHERE id=?",(i,))
  journal(c,i,'reprise : la proposition déjà reçue est disponible')
  return {'status':'proposed'}
 c.execute("UPDATE mc_jobs SET status='queued',finished_at=NULL WHERE id=?",(i,))
 journal(c,i,'reprise : appel du modèle')
 threading.Thread(target=contextvars.copy_context().run,args=(job_en_arriere,i),daemon=True).start()
 return {'status':'queued'}

def job_en_arriere(i,genere=None):
 with connect() as authorization:
  bound=one(authorization,'SELECT project_id FROM mc_jobs WHERE id=?',(i,))
  mc_security.require(authorization,bound['project_id'],'job_run',job=i)
 try:job_executer(i,genere)
 except Exception as e:
  with LOCK,connect() as c:
   c.execute("UPDATE mc_jobs SET status='failed',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",(str(e)[:2000],i))
   journal(c,i,'échec : '+str(e)[:300])

def job_executer(i,genere=None):
 with connect() as authorization:
  bound=one(authorization,'SELECT project_id FROM mc_jobs WHERE id=?',(i,))
  mc_security.require(authorization,bound['project_id'],'job_run',job=i)
 injecte=genere is not None
 with LOCK,connect() as c:
  j=one(c,'SELECT * FROM mc_jobs WHERE id=?',(i,))
  pris=c.execute("UPDATE mc_jobs SET status='running',started_at=CURRENT_TIMESTAMP,error='' WHERE id=? AND status IN ('queued','blocked')",(i,)).rowcount
  if pris!=1:
   return {'status':'deja_pris','id':i}
  journal(c,i,'exécution · modèle %s'%j['model'])
  audit(c,j['project_id'],'job_started',{'id':i})
 racine=Path(j['workspace'])
 try:
  with LOCK,connect() as c:contexte=json.dumps(context_packet(c,j['project_id'],j['agent_id']),ensure_ascii=False)
  existant=mc_agent.lire_contexte(racine)
  if existant:contexte+='\n\nFichiers autorisés déjà présents dans le workspace:\n'+existant
  if injecte:proposition=genere(j['model'],j['task'],contexte)
  else:
   with connect() as provider_db:
    proposition=mc_connectors.generate(provider_db,j['project_id'],j['agent_id'],mc_agent.SYSTEME,j['task']+'\n\nContexte:\n'+contexte)
   if proposition is None:proposition=mc_agent.generer_ollama(j['model'],mc_agent.SYSTEME,j['task'],contexte)
  with _verrous:annule=i in _annulations
  if annule:raise mc_agent.Refus('Job annulé avant proposition')
  with connect() as authorization:mc_security.require(authorization,j['project_id'],'job_run',job=i)
  fichiers=mc_agent.valider_proposition(racine,proposition)
  difference=mc_agent.diff(racine,fichiers)
  with _verrous:en_pause=i in _pauses;_pauses.discard(i)
  statut='paused' if en_pause else 'proposed'
  with LOCK,connect() as c:
   texte_proposition=json.dumps(proposition,ensure_ascii=False)
   if len(texte_proposition)>MAX_TEXTE:raise ValueError('Proposition trop volumineuse (%d caractères, maximum %d) : rien n’a été enregistré'%(len(texte_proposition),MAX_TEXTE))
   if len(difference)>MAX_TEXTE:raise ValueError('Diff trop volumineux (%d caractères, maximum %d) : rien n’a été enregistré'%(len(difference),MAX_TEXTE))
   c.execute("UPDATE mc_jobs SET status=?,proposal=?,diff=? WHERE id=? AND status='running'",(statut,texte_proposition,difference,i))
   journal(c,i,'%s : %d fichier(s) · %s'%('proposition' if statut=='proposed' else 'pause',len(fichiers),', '.join(str(f[0].relative_to(racine)) for f in fichiers)[:300]))
   audit(c,j['project_id'],'job_'+statut,{'id':i,'fichiers':[str(f[0].relative_to(racine)) for f in fichiers]})
  return {'status':statut}
 except Exception as e:
  with LOCK,connect() as c:
   statut='cancelled' if i in _annulations else 'failed'
   c.execute("UPDATE mc_jobs SET status=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",(statut,str(e)[:2000],i))
   journal(c,i,statut+' : '+str(e)[:300])
   audit(c,j['project_id'],'job_'+statut,{'id':i,'error':str(e)[:500]})
  with _verrous:_annulations.discard(i);_pauses.discard(i)
  return {'status':statut,'error':str(e)}

def job_approuver(c,p,i,d=None):
 acteur(c,p,d or {},'can_approve_jobs')
 j=job_publie(c,p,i)
 if j['status']!='proposed':raise ValueError('Aucune proposition à approuver ('+j['status']+')')
 racine=Path(j['workspace'])
 fichiers=mc_agent.valider_proposition(racine,json.loads(j['proposal']))
 ecrits=mc_agent.appliquer(racine,fichiers)
 c.execute("UPDATE mc_jobs SET status='approved',finished_at=CURRENT_TIMESTAMP WHERE id=?",(i,))
 journal(c,i,'approuvé et écrit : '+', '.join(e['path'] for e in ecrits)[:300])
 audit(c,p,'job_approved',{'id':i,'fichiers':[e['path'] for e in ecrits]})
 return {'fichiers':ecrits}

def job_refuser(c,p,i,d):
 j=job_publie(c,p,i)
 if j['status'] not in ('proposed','paused'):raise ValueError('On ne refuse pas un travail déjà appliqué ('+j['status']+') : utilisez git ou la restauration')
 motif=str(d.get('reason','Refusé par un humain'))[:500]
 c.execute("UPDATE mc_jobs SET status='cancelled',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",(motif,i))
 journal(c,i,'refusé : '+motif[:200])
 audit(c,p,'job_rejected',{'id':i,'raison':motif[:300]})
 return {'ok':True}

def job_annuler(c,p,i):
 j=job_publie(c,p,i)
 if j['status'] in ('approved','completed'):raise ValueError('Job déjà appliqué : on ne l’annule plus')
 _annulations.add(i);_pauses.discard(i)
 c.execute("UPDATE mc_jobs SET status='cancelled',finished_at=CURRENT_TIMESTAMP WHERE id=?",(i,))
 journal(c,i,'annulé par un humain')
 audit(c,p,'job_cancelled',{'id':i})
 return {'ok':True}

def job_tester(c,p,i,d):
 acteur(c,p,d,'can_run_tests')
 j=job_publie(c,p,i)
 if j['status'] not in ('approved','completed'):
  raise ValueError('On ne teste pas un travail non appliqué (statut '+j['status']+')')
 if not j['workspace']:raise ValueError('Workspace absent')
 racine=Path(j['workspace'])
 resultat=mc_agent.executer_commande(racine,required_text(d,'command',40),d.get('file'))
 resultat['at']=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
 resultat['job_id']=j['id']
 preuve=json.dumps(resultat,ensure_ascii=False)
 if len(preuve)>MAX_PREUVE:raise ValueError('Preuve trop volumineuse (%d caractères, maximum %d)'%(len(preuve),MAX_PREUVE))
 c.execute('UPDATE mc_jobs SET evidence=? WHERE id=?',(preuve,i))
 statut='completed' if j['status']=='approved' and resultat['exit_code']==0 else j['status']
 if statut!=j['status']:c.execute("UPDATE mc_jobs SET status='completed' WHERE id=?",(i,))
 journal(c,i,'test %s → code %s (%s ms)'%(resultat['command'],resultat['exit_code'],resultat['duration_ms']))
 if j['assignment_id'] and resultat['exit_code']==0:
  c.execute("UPDATE mc_assignments SET verification='test',verified=1,evidence=?,verified_at=? WHERE id=?",(preuve,resultat['at'],j['assignment_id']))
 audit(c,p,'job_tested',{'id':i,'command':resultat['command'],'exit_code':resultat['exit_code']})
 return {'evidence':resultat,'status':statut}

# --- P5 : revue, validation, commit, rapport --------------------------------
def review_creer(c,p,d):
 j=job_publie(c,p,int(d['job_id']))
 if j['status'] not in ('approved','completed'):raise ValueError('On ne révise qu’un travail déjà appliqué')
 kind=required_text(d,'kind',20)
 if kind not in ('code','tests','securite'):raise ValueError('Type de revue inconnu (code, tests, securite)')
 aid=d.get('agent_id');aid=int(aid) if aid not in ('',None) else None
 if aid:agent(c,p,aid)
 if kind=='securite':
  constats=mc_agent.analyser_diff(j['diff'])
  verdict='probleme' if constats else 'ok'
 else:
  verdict=str(d.get('verdict','')).strip()
  if verdict not in ('ok','probleme'):raise ValueError('Verdict invalide (ok ou probleme)')
  constats=[str(x)[:500] for x in (d.get('findings') or []) if str(x).strip()][:50]
 cur=c.execute('INSERT INTO mc_reviews(project_id,job_id,agent_id,kind,verdict,findings) VALUES(?,?,?,?,?,?)',(p,j['id'],aid,kind,verdict,json.dumps(constats,ensure_ascii=False)[:8000]))
 journal(c,j['id'],'revue %s : %s (%d constat(s))'%(kind,verdict,len(constats)))
 audit(c,p,'review_recorded',{'id':cur.lastrowid,'job':j['id'],'kind':kind,'verdict':verdict})
 return {'id':cur.lastrowid,'verdict':verdict,'findings':constats}

def job_valider(c,p,d):
 acteur(c,p,d,'can_approve_jobs')
 j=job_publie(c,p,int(d['id']))
 if j['status'] not in ('approved','completed'):raise ValueError('Seul un travail appliqué peut être validé')
 try:preuve=json.loads(j['evidence'] or '{}')
 except ValueError:preuve={}
 if preuve.get('exit_code')!=0:
  raise ValueError('Aucun test réussi enregistré : lance d’abord « Lancer les tests »')
 revues=rows(c,'SELECT kind,verdict FROM mc_reviews WHERE job_id=?',(j['id'],))
 if not revues:raise ValueError('Aucune revue enregistrée : demande une revue avant de valider')
 mauvaises=[r['kind'] for r in revues if r['verdict']!='ok']
 if mauvaises:raise ValueError('Revue(s) en échec : '+', '.join(mauvaises))
 maintenant=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
 c.execute("UPDATE mc_jobs SET status='completed',finished_at=CURRENT_TIMESTAMP WHERE id=?",(j['id'],))
 journal(c,j['id'],'validé : tests verts et revues favorables')
 if j['assignment_id']:
  c.execute("UPDATE mc_assignments SET verification='validated',verified=1,evidence=?,verified_at=? WHERE id=?",(j['evidence'],maintenant,j['assignment_id']))
 audit(c,p,'job_validated',{'id':j['id'],'revues':[r['kind'] for r in revues]})
 return {'ok':True,'verification':'validated'}

def job_commit(c,p,d):
 acteur(c,p,d,'can_approve_jobs')
 j=job_publie(c,p,int(d['id']))
 if j['status'] not in ('approved','completed'):raise ValueError('Seul un travail appliqué peut être commité')
 message=str(d.get('message') or ('BM318d job %d : %s'%(j['id'],j['title'])))[:200]
 resultat=mc_agent.commit_git(Path(j['workspace']),message)
 try:preuve=json.loads(j['evidence'] or '{}')
 except ValueError:preuve={}
 preuve['commit']=resultat.get('commit')
 preuve['commit_message']=resultat.get('message')
 c.execute('UPDATE mc_jobs SET evidence=? WHERE id=?',(json.dumps(preuve,ensure_ascii=False)[:8000],j['id']))
 journal(c,j['id'],'commit '+str(resultat.get('commit')))
 audit(c,p,'job_committed',{'id':j['id'],'commit':resultat.get('commit')})
 return resultat

def rapport_job(c,p,i):
 j=job_publie(c,p,i)
 revues=rows(c,'SELECT kind,verdict,findings,created_at FROM mc_reviews WHERE job_id=? ORDER BY id',(i,))
 try:preuve=json.loads(j['evidence'] or '{}')
 except ValueError:preuve={}
 return {'job':{k:j[k] for k in ('id','title','task','status','model','workspace','created_at','started_at','finished_at')},
  'proposal':j['proposal'],'diff':j['diff'],'evidence':preuve,'reviews':revues,'log':j['log']}
# --- P6 : roles personnalises, recrutement, equipes --------------------------
def roles_projet(c,p):
 perso=rows(c,'SELECT key,label,description FROM mc_roles WHERE project_id=? ORDER BY key',(p,))
 base=[{'key':k,'label':k.capitalize(),'description':'','builtin':True} for k in ROLES]
 return base+[dict(r,builtin=False) for r in perso]

def role_valide(c,p,role):
 return any(r['key']==role for r in roles_projet(c,p))

def role_creer(c,p,d):
 cle=required_text(d,'key',40)
 if cle in ROLES:raise ValueError('Ce rôle existe déjà dans la bibliothèque de base')
 if not re.match(r'^[a-z][a-z0-9_-]{1,39}$',cle):raise ValueError('Clé de rôle invalide (minuscules, chiffres, tiret)')
 label=required_text(d,'label',80);description=str(d.get('description',''))[:400]
 c.execute('INSERT OR REPLACE INTO mc_roles(project_id,key,label,description) VALUES(?,?,?,?)',(p,cle,label,description))
 audit(c,p,'role_created',{'key':cle,'label':label});return {'key':cle,'label':label}

def permission(c,p,equipe,action):
 # Ferme par defaut : une equipe sans ligne de permissions n'a aucun droit.
 ligne=rows(c,'SELECT can_create_agents,can_approve_jobs,can_run_tests FROM mc_team_permissions WHERE project_id=? AND team=?',(p,equipe))
 if not ligne:return False
 return bool(ligne[0].get(action,0))

def permissions_lire(c,p):
 equipes=rows(c,"SELECT DISTINCT team FROM mc_agents WHERE project_id=? UNION SELECT team FROM mc_team_permissions WHERE project_id=? ORDER BY team",(p,p))
 return [dict(team=e['team'],
  can_create_agents=permission(c,p,e['team'],'can_create_agents'),
  can_approve_jobs=permission(c,p,e['team'],'can_approve_jobs'),
  can_run_tests=permission(c,p,e['team'],'can_run_tests')) for e in equipes]

def permissions_definir(c,p,d):
 equipe=required_text(d,'team',80)
 c.execute('INSERT INTO mc_team_permissions(project_id,team,can_create_agents,can_approve_jobs,can_run_tests) VALUES(?,?,?,?,?) ON CONFLICT(project_id,team) DO UPDATE SET can_create_agents=excluded.can_create_agents,can_approve_jobs=excluded.can_approve_jobs,can_run_tests=excluded.can_run_tests',(p,equipe,int(bool(d.get('can_create_agents',True))),int(bool(d.get('can_approve_jobs',True))),int(bool(d.get('can_run_tests',True)))))
 audit(c,p,'team_permissions',{'team':equipe});return {'ok':True}

def branche_creer(c,p,d):
 nom=required_text(d,'name',80)
 architecte=d.get('architect_id');architecte=int(architecte) if architecte not in ('',None) else None
 if architecte:agent(c,p,architecte)
 cur=c.execute('INSERT INTO mc_branches(project_id,name,architect_id,description) VALUES(?,?,?,?)',(p,nom,architecte,str(d.get('description',''))[:400]))
 audit(c,p,'branch_created',{'id':cur.lastrowid,'name':nom});return {'id':cur.lastrowid}

def branche_modifier(c,p,d):
 b=one(c,'SELECT * FROM mc_branches WHERE project_id=? AND id=?',(p,int(d['id'])))
 updates={}
 if 'name' in d:
  nom=str(d['name']).strip()[:80]
  if not nom:raise ValueError('Nom de branche vide')
  updates['name']=nom
 if 'description' in d:updates['description']=str(d['description'])[:400]
 if 'architect_id' in d:
  architecte=d['architect_id'];architecte=int(architecte) if architecte not in ('',None) else None
  if architecte:agent(c,p,architecte)
  updates['architect_id']=architecte
 if not updates:raise ValueError('Aucun changement')
 c.execute('UPDATE mc_branches SET '+','.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),b['id']))
 audit(c,p,'branch_updated',{'id':b['id'],'changes':list(updates)});return {'ok':True}

def acteur(c,p,d,action=None):
 """Identite obligatoire : toute action sensible designe l'agent qui l'exerce."""
 identifiant=d.get('agent_id')
 if identifiant in ('',None):raise ValueError('Agent (agent_id) requis pour cette action')
 a=agent(c,p,int(identifiant))
 identity=mc_security.current()
 if identity.kind=='agent' and identity.agent!=a['id']:raise mc_security.Refus('Usurpation d’identité agent refusée')
 if action and not permission(c,p,a['team'],action):
  raise ValueError('L’équipe '+a['team']+' n’a pas le droit : '+action)
 return a

def agent_clone(c,p,d):
 source=agent(c,p,int(d['id']))
 nom=str(d.get('name') or (source['name']+' (copie)'))[:100]
 cur=c.execute('INSERT INTO mc_agents(project_id,name,role,team,manager_id,status,model,instructions,x,y) VALUES(?,?,?,?,?,?,?,?,?,?)',(p,nom,source['role'],source['team'],source['manager_id'],'idle',source['model'],source['instructions'],source['x']+60,source['y']+60))
 audit(c,p,'agent_cloned',{'source':source['id'],'id':cur.lastrowid});return {'id':cur.lastrowid,'name':nom}

def recrue_creer(c,p,d):
 role=required_text(d,'role',40)
 if not role_valide(c,p,role):raise ValueError('Rôle inconnu')
 nom=required_text(d,'name',100)
 equipe=str(d.get('team','Général')).strip()[:80] or 'Général'
 justification=required_text(d,'justification',1000)
 modele=str(d.get('model') or '')[:80]
 cur=c.execute('INSERT INTO mc_recruits(project_id,name,role,team,model,justification) VALUES(?,?,?,?,?,?)',(p,nom,role,equipe,modele,justification))
 audit(c,p,'recruit_requested',{'id':cur.lastrowid,'name':nom,'role':role})
 return {'id':cur.lastrowid,'status':'pending'}

def recrue_decider(c,p,d):
 recrue=one(c,'SELECT * FROM mc_recruits WHERE project_id=? AND id=?',(p,int(d['id'])))
 if recrue['status']!='pending':raise ValueError('Recrutement déjà tranché ('+recrue['status']+')')
 decideur=d.get('agent_id');decideur=int(decideur) if decideur not in ('',None) else None
 if decideur:agent(c,p,decideur)
 accepter=bool(d.get('approve',True))
 if accepter:
  if decideur and not permission(c,p,agent(c,p,decideur)['team'],'can_create_agents'):
   raise ValueError('Cette équipe n’a pas le droit de recruter')
  cur=c.execute('INSERT INTO mc_agents(project_id,name,role,team,manager_id,status,model,instructions,x,y) VALUES(?,?,?,?,?,?,?,?,?,?)',(p,recrue['name'],recrue['role'],recrue['team'],None,'idle',recrue['model'] or 'qwen3.5:4b','Recruté : '+recrue['justification'],140,120))
  identifiant=cur.lastrowid
  c.execute("UPDATE mc_recruits SET status='approved',decided_at=CURRENT_TIMESTAMP,decided_by=? WHERE id=?",(decideur,recrue['id']))
  audit(c,p,'recruit_approved',{'id':recrue['id'],'agent':identifiant})
  return {'status':'approved','agent_id':identifiant}
 c.execute("UPDATE mc_recruits SET status='rejected',decided_at=CURRENT_TIMESTAMP,decided_by=? WHERE id=?",(decideur,recrue['id']))
 audit(c,p,'recruit_rejected',{'id':recrue['id']})
 return {'status':'rejected'}

def agent_archiver(c,p,d):
 a=agent(c,p,int(d['id']))
 c.execute("UPDATE mc_agents SET status='archived' WHERE id=?",(a['id'],))
 audit(c,p,'agent_archived',{'id':a['id']});return {'ok':True}

# --- P2 : planification et orchestration -------------------------------------
SYSTEME_PLAN=(
 'Tu es chef de projet. Tu réponds UNIQUEMENT par un objet JSON valide, sans texte autour, '
 'de la forme {"objective": "une phrase", "tasks": [{"title": "...", "task": "...", '
 '"role": "backend", "depends_on": []}]}. '
 'Au plus 8 tâches. "depends_on" contient les indices (à partir de 0) des tâches prérequises. '
 'Rôles autorisés : '+', '.join(mc_plan.ROLES)+'. '
 'Découpe en tâches réellement exécutables, avec des dépendances justes.'
)

def charge_par_agent(c,p):
 return {r['agent_id']:r['n'] for r in rows(c,"SELECT agent_id,count(*) AS n FROM mc_jobs WHERE project_id=? AND status IN ('queued','running','paused','proposed') GROUP BY agent_id",(p,))}

def plan_proposer(c,p,d,genere=None):
 genere=genere or (lambda modele,tache,contexte:mc_agent.generer_ollama(modele,SYSTEME_PLAN,tache,contexte))
 objectif=required_text(d,'objective',2000)
 mission=d.get('mission_id');mission=int(mission) if mission not in ('',None) else None
 if mission is not None:one(c,'SELECT * FROM mc_missions WHERE project_id=? AND id=?',(p,mission))
 agents=rows(c,'SELECT id,name,role,team,status,model FROM mc_agents WHERE project_id=? ORDER BY id',(p,))
 if not agents:raise ValueError('Aucun agent : la planification demande au moins un agent')
 modele=str(d.get('model') or agents[0]['model'] or 'qwen3.5:4b')[:80]
 contexte=json.dumps({'agents':[{'name':a['name'],'role':a['role'],'team':a['team'],'status':a['status']} for a in agents]},ensure_ascii=False)
 plan=mc_plan.valider_plan(genere(modele,objectif,contexte),roles={r['key'] for r in roles_projet(c,p)})
 charge=charge_par_agent(c,p)
 affectations={}
 for t in plan['tasks']:
  a=mc_plan.choisir_agent(agents,t['role'],charge)
  affectations[str(t['index'])]={'agent_id':a['id'] if a else None,'agent':a['name'] if a else None,'role':t['role']}
 manquants=sorted({v['role'] for v in affectations.values() if not v['agent_id']})
 cur=c.execute('INSERT INTO mc_plans(project_id,mission_id,objective,tasks,assignments) VALUES(?,?,?,?,?)',(p,mission,objectif,json.dumps(plan,ensure_ascii=False),json.dumps(affectations,ensure_ascii=False)))
 plan_id=cur.lastrowid
 audit(c,p,'plan_proposed',{'id':plan_id,'taches':len(plan['tasks']),'sans_agent':manquants})
 return {'id':plan_id,'plan':plan,'assignations':affectations,'roles_sans_agent':manquants}

def plan_appliquer(c,p,d):
 plan_id=int(d['id'])
 ligne=one(c,'SELECT * FROM mc_plans WHERE project_id=? AND id=?',(p,plan_id))
 if ligne['status']!='proposed':raise ValueError('Ce plan a déjà été appliqué ('+ligne['status']+')')
 plan=json.loads(ligne['tasks']);affectations=json.loads(ligne['assignments'] or '{}')
 manquants=sorted({v['role'] for v in affectations.values() if not v.get('agent_id')})
 if manquants:raise ValueError('Aucun agent pour le(s) rôle(s) : '+', '.join(manquants))
 ids={}
 for t in plan['tasks']:
  cree=job_creer(c,p,{'agent_id':affectations[str(t['index'])]['agent_id'],'title':t['title'],'task':t['task'],'mission_id':ligne['mission_id']})
  ids[str(t['index'])]=cree['id']
 for t in plan['tasks']:
  for indice in t['depends_on']:
   c.execute('INSERT OR IGNORE INTO mc_job_deps(job_id,depends_on) VALUES(?,?)',(ids[str(t['index'])],ids[str(indice)]))
 c.execute("UPDATE mc_plans SET status='applied' WHERE id=?",(plan_id,))
 audit(c,p,'plan_applied',{'id':plan_id,'jobs':list(ids.values())})
 return {'jobs':ids}

def orchestrateur_lancer(c,p,d):
 limite=mc_plan.executions_simultanees()
 en_cours=len(rows(c,"SELECT id FROM mc_jobs WHERE project_id=? AND status='running'",(p,)))
 libres=max(0,limite-en_cours)
 if libres<=0:return {'lances':[],'limite':limite,'en_cours':en_cours,'message':'limite de mémoire atteinte'}
 prets=[]
 for j in rows(c,"SELECT * FROM mc_jobs WHERE project_id=? AND status IN ('queued','blocked') ORDER BY id",(p,)):
  deps=[r['depends_on'] for r in rows(c,'SELECT depends_on FROM mc_job_deps WHERE job_id=?',(j['id'],))]
  if j['depends_on'] and j['depends_on'] not in deps:deps.append(j['depends_on'])
  valide=True
  for dep_id in deps:
   try:dep=job_publie(c,p,dep_id)
   except ValueError:dep=None
   if not dep or dep['status'] not in ('approved','completed'):valide=False;break
  if valide:prets.append(j)
 lances=[]
 for j in prets[:libres]:
  job_lancer(c,p,j['id'])
  lances.append(j['id'])
 audit(c,p,'orchestrator_run',{'lances':lances,'limite':limite})
 return {'lances':lances,'limite':limite,'en_cours':en_cours,'prets':len(prets)}

def charge_agents(c,p):
 agents=rows(c,'SELECT id,name,role,team,status FROM mc_agents WHERE project_id=? ORDER BY id',(p,))
 charge=charge_par_agent(c,p)
 jobs=rows(c,'SELECT agent_id,status,count(*) AS n FROM mc_jobs WHERE project_id=? GROUP BY agent_id,status',(p,))
 par_agent={}
 for ligne in jobs:par_agent.setdefault(ligne['agent_id'],{})[ligne['status']]=ligne['n']
 non_lus=rows(c,'SELECT to_agent,count(*) AS n FROM mc_messages WHERE project_id=? AND read_at IS NULL AND to_agent IS NOT NULL GROUP BY to_agent',(p,))
 lus={r['to_agent']:r['n'] for r in non_lus}
 details=[]
 for a in agents:
  etats=par_agent.get(a['id'],{})
  details.append(dict(a,charge=charge.get(a['id'],0),
   en_cours=etats.get('running',0),en_attente=etats.get('queued',0)+etats.get('blocked',0),
   termines=etats.get('completed',0),echecs=etats.get('failed',0),
   messages_non_lus=lus.get(a['id'],0),
   disponible=a['status'] not in ('archived','paused') and etats.get('running',0)==0))
 suggestions=[]
 for j in rows(c,"SELECT * FROM mc_jobs WHERE project_id=? AND status='failed' ORDER BY id DESC LIMIT 10",(p,)):
  actuel=next((a for a in agents if a['id']==j['agent_id']),None)
  if not actuel:continue
  candidats=[a for a in agents if a['role']==actuel['role'] and a['id']!=actuel['id'] and a['status']!='archived']
  if candidats:
   meilleur=min(candidats,key=lambda a:charge.get(a['id'],0))
   suggestions.append({'job':j['id'],'titre':j['title'],'agent_actuel':actuel['name'],'vers':meilleur['name'],'vers_id':meilleur['id'],'charge':charge.get(meilleur['id'],0)})
 total={'agents':len(agents),'actifs':sum(1 for a in agents if a['status']!='archived'),
  'archives':sum(1 for a in agents if a['status']=='archived'),
  'en_cours':sum(d['en_cours'] for d in details),'echecs':sum(d['echecs'] for d in details),
  'non_lus':sum(d['messages_non_lus'] for d in details)}
 return {'agents':details,'total':total,'suggestions':suggestions,'memoire_libre_mo':mc_plan.memoire_libre_mo(),
  'cpu_pct':mc_plan.cpu_charge(),'gpu':mc_plan.gpu_info(),'limite':mc_plan.executions_simultanees()}

# --- P7 : application, reglages, recherche, sauvegardes ----------------------
SERVEUR=[None]
VERSION='2.2.0'
MAX_TEXTE=200000
MAX_PREUVE=8000
ADMIN_TOKEN=os.environ.get('MC_ADMIN_TOKEN') or secrets.token_urlsafe(24)
mc_security.configure(TOKEN,ADMIN_TOKEN)
MANIFESTE=ROOT/'installer'/'version.json'
REGLAGES_DEFAUT={'ollama_url':'http://127.0.0.1:11434/api/chat','ollama_model':'qwen3.5:4b',
 'max_jobs':'','auto_backup_minutes':'60','workspace_dir':str(mc_agent.WORKSPACES)}

def reglages(c,p):
 valeurs=dict(REGLAGES_DEFAUT)
 for ligne in rows(c,'SELECT key,value FROM mc_settings WHERE project_id=?',(p,)):valeurs[ligne['key']]=ligne['value']
 return valeurs

def reglage_definir(c,p,d):
 cle=required_text(d,'key',40)
 if cle not in REGLAGES_DEFAUT:raise ValueError('Réglage inconnu : '+cle)
 valeur=str(d.get('value','')).strip()[:300]
 c.execute('INSERT INTO mc_settings(project_id,key,value) VALUES(?,?,?) ON CONFLICT(project_id,key) DO UPDATE SET value=excluded.value',(p,cle,valeur))
 if cle=='ollama_url' and valeur:mc_agent.OLLAMA=valeur
 if cle=='max_jobs':os.environ['MC_MAX_JOBS']=valeur
 if cle=='workspace_dir':
  if not valeur:raise ValueError('Le dossier des workspaces ne peut pas être vide')
  cible=Path(valeur).expanduser()
  if not cible.is_absolute():raise ValueError('Le dossier des workspaces doit être un chemin absolu')
  cible.mkdir(parents=True,exist_ok=True)
  mc_agent.WORKSPACES=cible.resolve()
 audit(c,p,'setting_changed',{'key':cle});return {'key':cle,'value':valeur}

def rechercher(c,p,q):
 terme=str(q or '').strip()
 if len(terme)<2:raise ValueError('Recherche : au moins 2 caractères')
 motif='%'+terme+'%'
 return {'terme':terme,
  'agents':rows(c,'SELECT id,name,role,team,status FROM mc_agents WHERE project_id=? AND (name LIKE ? OR instructions LIKE ?) LIMIT 10',(p,motif,motif)),
  'missions':rows(c,'SELECT id,title,status FROM mc_missions WHERE project_id=? AND (title LIKE ? OR objective LIKE ?) LIMIT 10',(p,motif,motif)),
  'jobs':rows(c,'SELECT id,title,status FROM mc_jobs WHERE project_id=? AND (title LIKE ? OR task LIKE ?) LIMIT 10',(p,motif,motif)),
  'notes':rows(c,'SELECT id,scope,content FROM mc_notes WHERE project_id=? AND content LIKE ? LIMIT 10',(p,motif)),
  'decisions':rows(c,'SELECT id,title,decision FROM mc_decisions WHERE project_id=? AND (title LIKE ? OR decision LIKE ? OR rationale LIKE ?) LIMIT 10',(p,motif,motif,motif)),
  'messages':rows(c,'SELECT id,body FROM mc_messages WHERE project_id=? AND body LIKE ? LIMIT 10',(p,motif))}

def notifications(c,p):
 return {'messages_non_lus':len(rows(c,'SELECT id FROM mc_messages WHERE project_id=? AND read_at IS NULL',(p,))),
  'recrutements_en_attente':len(rows(c,"SELECT id FROM mc_recruits WHERE project_id=? AND status='pending'",(p,))),
  'jobs_en_echec':len(rows(c,"SELECT id FROM mc_jobs WHERE project_id=? AND status='failed'",(p,))),
  'jobs_en_cours':len(rows(c,"SELECT id FROM mc_jobs WHERE project_id=? AND status='running'",(p,))),
  'passations_a_acquitter':len(rows(c,'SELECT id FROM mc_handoffs WHERE project_id=? AND ack_at IS NULL',(p,)))}

def historique(c,p,limite=80):
 return {'audit':rows(c,'SELECT action,details,created_at FROM mc_audit WHERE project_id=? ORDER BY id DESC LIMIT ?',(p,int(limite))),
  'jobs':rows(c,'SELECT id,title,status,created_at,finished_at FROM mc_jobs WHERE project_id=? ORDER BY id DESC LIMIT ?',(p,int(limite)))}

def sauvegardes_disponibles():
 base=ROOT/'backups'
 if not base.exists():return []
 return [{'nom':f.name,'octets':f.stat().st_size,'quand':datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec='seconds')}
  for f in sorted(base.glob('*.sqlite3'),key=lambda x:x.stat().st_mtime,reverse=True)[:30]]

def restaurer_sauvegarde(c,p,d):
 nom=required_text(d,'file',200)
 base=(ROOT/'backups').resolve()
 source=(base/nom).resolve()
 if source.parent!=base or not source.exists():
  raise ValueError('Sauvegarde introuvable dans backups/ : '+nom)
 securite=sauvegarder(ROOT/'backups'/('bm318d-avant-restauration-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3'))
 origine=sqlite3.connect(source);cible=sqlite3.connect(DB)
 try:origine.backup(cible)
 finally:cible.close();origine.close()
 init()  # Reapply additive migrations when restoring a pre-V2.2 database.
 audit(c,p,'database_restored',{'file':nom,'sauvegarde_prealable':securite.name})
 return {'ok':True,'sauvegarde_prealable':securite.name}

def demander_arret():
 threading.Thread(target=lambda: SERVEUR[0] and SERVEUR[0].shutdown(),daemon=True).start()
 return {'ok':True,'arret':'imminent'}

def rotation_sauvegardes(limite=10):
 base=ROOT/'backups'
 vieux=sorted(base.glob('bm318d-auto-*.sqlite3'),key=lambda x:x.stat().st_mtime,reverse=True)[limite:]
 for fichier in vieux:fichier.unlink(missing_ok=True)
 return len(vieux)

def boucle_sauvegardes(minutes):
 while True:
  time.sleep(max(60,int(minutes)*60))
  try:
   base=ROOT/'backups'
   sauvegarder(base/('bm318d-auto-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3'))
   rotation_sauvegardes(10)
  except Exception:
   pass

def _dispatch(c,path,d):
 mc_security.authorize_route(c,path,d)
 p=int(d.get('project',0));project(c,p)
 if path=='/api/mc/security/token':
  a=agent(c,p,int(d['agent_id']))
  if a['status']=='archived':raise ValueError('Agent archivé')
  return mc_security.issue(p,a['id'],d.get('actions'),int(d.get('ttl',900)))
 if path=='/api/mc/security/revoke':
  mc_security.revoke(required_text(d,'grant_id',100));return {'revoked':True}
 if path.startswith('/api/mc/connectors/'):
  return mc_connectors.dispatch(c,p,path.rsplit('/',1)[-1],d)
 if path=='/api/mc/agent':
  name=required_text(d,'name',100);role=required_text(d,'role',40)
  if not role_valide(c,p,role):raise ValueError('Rôle inconnu')
  team=str(d.get('team','Général')).strip()[:80] or 'Général'
  manager=d.get('manager_id');manager=int(manager) if manager not in ('',None) else None
  if manager:agent(c,p,manager)
  cur=c.execute('INSERT INTO mc_agents(project_id,name,role,team,manager_id,x,y,instructions,skills) VALUES(?,?,?,?,?,?,?,?,?)',(p,name,role,team,manager,int(d.get('x',120)),int(d.get('y',120)),str(d.get('instructions',''))[:2000],str(d.get('skills',''))[:300]))
  c.execute('INSERT OR IGNORE INTO mc_team_permissions(project_id,team) VALUES(?,?)',(p,team))
  audit(c,p,'agent_created',{'id':cur.lastrowid,'name':name});return {'id':cur.lastrowid}
 if path=='/api/mc/agent/update':
  i=int(d['id']);a=agent(c,p,i)
  updates={}
  for k in ('name','team','instructions','model','skills'):
   if k in d:updates[k]=str(d[k]).strip()[:(2000 if k=='instructions' else 100)]
  if 'role' in d:
   if not role_valide(c,p,d['role']):raise ValueError('Rôle inconnu')
   updates['role']=d['role']
  if 'status' in d:
   if d['status'] not in STATUSES:raise ValueError('Statut invalide')
   updates['status']=d['status']
  for k in ('x','y'):
   if k in d:updates[k]=max(-10000,min(10000,int(d[k])))
  if 'manager_id' in d:
   manager=d['manager_id'];manager=int(manager) if manager not in (None,'') else None
   if manager:agent(c,p,manager)
   hierarchy_cycle(c,p,i,manager)
   updates['manager_id']=manager
   if manager!=a['manager_id']:
    summary=('Transfert de '+a['name']+' ('+a['role']+') depuis '+str(a['manager_id'])+' vers '+str(manager)+'. Contexte conservé : tâches, notes, missions et historique. Nouvelle responsabilité à confirmer.')
    paquet=json.dumps(context_packet(c,p,i),ensure_ascii=False)
    cur=c.execute('INSERT INTO mc_handoffs(project_id,agent_id,old_manager_id,new_manager_id,summary,context) VALUES(?,?,?,?,?,?)',(p,i,a['manager_id'],manager,summary,paquet))
    # Transmission réelle : le nouveau responsable reçoit un message ciblé à acquitter.
    if manager:
     c.execute('INSERT INTO mc_messages(project_id,from_agent,to_agent,body) VALUES(?,?,?,?)',(p,i,manager,'Passation n°%d : %s. Ouvre le dossier de contexte et confirme la prise en charge.'%(cur.lastrowid,summary[:600])))
     audit(c,p,'handoff_delivered',{'handoff':cur.lastrowid,'to':manager})
  if not updates:raise ValueError('Aucun changement')
  c.execute('UPDATE mc_agents SET '+','.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),i))
  audit(c,p,'agent_updated',{'id':i,'changes':updates});return {'id':i}
 if path=='/api/mc/link':
  a=int(d['source_id']);b=int(d['target_id']);kind=required_text(d,'kind',30)
  if a==b or kind not in ('communication','dependency'):raise ValueError('Lien invalide')
  agent(c,p,a);agent(c,p,b)
  if kind=='dependency':
   graph={}
   for r in rows(c,"SELECT source_id,target_id FROM mc_links WHERE project_id=? AND kind='dependency'",(p,)):graph.setdefault(r['source_id'],[]).append(r['target_id'])
   todo=[b];seen=set()
   while todo:
    x=todo.pop()
    if x==a:raise ValueError('Dépendance circulaire refusée')
    if x not in seen:seen.add(x);todo+=graph.get(x,[])
  c.execute('INSERT OR IGNORE INTO mc_links(project_id,source_id,target_id,kind) VALUES(?,?,?,?)',(p,a,b,kind))
  audit(c,p,'link_created',{'from':a,'to':b,'kind':kind});return {'ok':True}
 if path=='/api/mc/mission':
  title=required_text(d,'title',160);objective=required_text(d,'objective',5000)
  cur=c.execute('INSERT INTO mc_missions(project_id,title,objective) VALUES(?,?,?)',(p,title,objective))
  audit(c,p,'mission_created',{'id':cur.lastrowid});return {'id':cur.lastrowid}
 if path=='/api/mc/assignment':
  m=one(c,'SELECT * FROM mc_missions WHERE project_id=? AND id=?',(p,int(d['mission_id'])))
  a=agent(c,p,int(d['agent_id']));task=required_text(d,'task',2000)
  cur=c.execute('INSERT INTO mc_assignments(mission_id,agent_id,task) VALUES(?,?,?)',(m['id'],a['id'],task))
  audit(c,p,'assignment_created',{'id':cur.lastrowid,'agent':a['id']});return {'id':cur.lastrowid}
 if path=='/api/mc/assignment/update':
  a=one(c,'SELECT a.* FROM mc_assignments a JOIN mc_missions m ON a.mission_id=m.id WHERE a.id=? AND m.project_id=?',(int(d['id']),p))
  status=d.get('status',a['status'])
  if status not in ('queued','working','blocked','done','reviewed'):raise ValueError('Statut invalide')
  result=str(d.get('result',a['result']))[:8000]
  # Trois niveaux distincts, et une preuve obligatoire pour le troisieme :
  # declared = on affirme ; human = un humain a relu ; test = une commande a
  # reellement tourne, avec son code de sortie.
  verification=a['verification']
  if 'verification' in d:verification=str(d['verification'])
  elif d.get('verified') is True:verification='human' if status=='reviewed' else a['verification']
  if verification not in ('none','declared','human','test','approved','validated'):raise ValueError('Niveau de vérification inconnu')
  if verification in ('human','test','approved','validated') and status not in ('done','reviewed'):raise ValueError('On ne vérifie pas un travail encore en cours')
  evidence=a['evidence']
  if 'evidence' in d:
   if not isinstance(d['evidence'],dict):raise ValueError('Preuve invalide')
   evidence=json.dumps(d['evidence'],ensure_ascii=False)[:8000]
  if verification in ('test','validated'):
   try:prouve=json.loads(evidence or '{}')
   except ValueError:prouve={}
   if not str(prouve.get('command','')).strip() or not isinstance(prouve.get('exit_code'),int):
    raise ValueError('Preuve de test incomplète : commande et code de sortie (entier) requis')
   # La preuve doit venir d'un job réellement appliqué de ce projet.
   identifiant_job=prouve.get('job_id')
   if not isinstance(identifiant_job,int):
    raise ValueError('Preuve refusée : elle doit citer le job (job_id) qui l’a produite')
   job_source=one(c,'SELECT * FROM mc_jobs WHERE project_id=? AND id=?',(p,identifiant_job))
   if job_source['status'] not in ('approved','completed'):
    raise ValueError('Preuve refusée : le job '+str(identifiant_job)+' n’est pas appliqué')
   if job_source['assignment_id'] not in (None,a['id']):
    raise ValueError('Preuve refusée : elle appartient à une autre attribution')
  verified=1 if verification in ('human','test','approved','validated') else 0
  verifie_le=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds') if verified else a['verified_at']
  c.execute('UPDATE mc_assignments SET status=?,result=?,verified=?,verification=?,evidence=?,verified_at=? WHERE id=?',(status,result,verified,verification,evidence,verifie_le,a['id']))
  audit(c,p,'assignment_updated',{'id':a['id'],'status':status,'verification':verification,'verified':verified});return {'ok':True,'verification':verification}
 if path=='/api/mc/note':
  aid=d.get('agent_id');aid=int(aid) if aid not in ('',None) else None
  if aid:agent(c,p,aid)
  scope=d.get('scope','project')
  if scope not in ('project','team','agent'):raise ValueError('Portée invalide')
  equipe=str(d.get('team') or '').strip()[:80] or None
  if scope=='team' and not equipe and aid:equipe=agent(c,p,aid)['team']
  if scope=='team' and not equipe:raise ValueError('Une note d’équipe demande une équipe')
  remplasse=d.get('supersedes');remplasse=int(remplasse) if remplasse not in ('',None) else None
  if remplasse is not None:
   ancienne=one(c,'SELECT * FROM mc_notes WHERE project_id=? AND id=?',(p,remplasse))
   if ancienne['scope']!=scope:raise ValueError('On ne remplace pas une note d’une autre portée')
   if scope=='agent' and ancienne['agent_id']!=aid:raise mc_security.Refus('On ne remplace pas la note privée d’un autre agent')
   if scope=='team' and ancienne['team']!=equipe:raise mc_security.Refus('On ne remplace pas la note d’une autre équipe')
  content=required_text(d,'content',4000)
  cur=c.execute('INSERT INTO mc_notes(project_id,agent_id,scope,team,supersedes,content) VALUES(?,?,?,?,?,?)',(p,aid,scope,equipe,remplasse,content))
  audit(c,p,'note_created',{'id':cur.lastrowid,'scope':scope,'remplace':remplasse});return {'id':cur.lastrowid}
 if path=='/api/mc/decision':
  aid=d.get('agent_id');aid=int(aid) if aid not in ('',None) else None
  if aid:agent(c,p,aid)
  titre=required_text(d,'title',160);decision=required_text(d,'decision',4000);raison=required_text(d,'rationale',4000)
  alternative=str(d.get('alternatives',''))[:4000]
  cur=c.execute('INSERT INTO mc_decisions(project_id,agent_id,title,decision,rationale,alternatives) VALUES(?,?,?,?,?,?)',(p,aid,titre,decision,raison,alternative))
  audit(c,p,'decision_recorded',{'id':cur.lastrowid,'title':titre});return {'id':cur.lastrowid}
 if path=='/api/mc/message':
  de=d.get('from_agent');de=int(de) if de not in ('',None) else None
  vers=d.get('to_agent');vers=int(vers) if vers not in ('',None) else None
  equipe=str(d.get('to_team') or '').strip()[:80] or None
  if de:agent(c,p,de)
  if vers:agent(c,p,vers)
  if bool(vers)==bool(equipe):raise ValueError('Un message vise un agent ou une équipe, pas les deux ni aucun')
  corps=required_text(d,'body',4000)
  cur=c.execute('INSERT INTO mc_messages(project_id,from_agent,to_agent,to_team,body) VALUES(?,?,?,?,?)',(p,de,vers,equipe,corps))
  audit(c,p,'message_sent',{'id':cur.lastrowid,'vers_agent':vers,'vers_equipe':equipe});return {'id':cur.lastrowid}
 if path=='/api/mc/message/read':
  j=one(c,'SELECT * FROM mc_messages WHERE project_id=? AND id=?',(p,int(d['id'])))
  aid=int(d['agent_id']);a=agent(c,p,aid)
  if not (j['to_agent']==aid or (j['to_team'] and j['to_team']==a['team'])):
   raise ValueError('Ce message ne te concerne pas')
  if not j['read_at']:
   c.execute("UPDATE mc_messages SET read_at=CURRENT_TIMESTAMP WHERE id=?",(j['id'],))
   audit(c,p,'message_read',{'id':j['id'],'agent':aid})
  return {'ok':True,'deja_lu':bool(j['read_at'])}
 if path=='/api/mc/handoff/ack':
  j=one(c,'SELECT * FROM mc_handoffs WHERE project_id=? AND id=?',(p,int(d['id'])))
  aid=int(d['agent_id']);agent(c,p,aid)
  if j['new_manager_id']!=aid:raise ValueError('Seul le nouveau responsable peut acquitter cette passation')
  if j['ack_at']:raise ValueError('Passation déjà acquittée')
  c.execute("UPDATE mc_handoffs SET ack_at=CURRENT_TIMESTAMP,ack_by=? WHERE id=?",(aid,j['id']))
  audit(c,p,'handoff_acknowledged',{'id':j['id'],'agent':aid})
  return {'ok':True}
 if path=='/api/mc/job':return job_creer(c,p,d)
 if path=='/api/mc/job/run':return job_lancer(c,p,int(d['id']))
 if path=='/api/mc/job/pause':return job_pause(c,p,int(d['id']))
 if path=='/api/mc/job/resume':return job_reprendre(c,p,int(d['id']))
 if path=='/api/mc/job/approve':return job_approuver(c,p,int(d['id']),d)
 if path=='/api/mc/job/reject':return job_refuser(c,p,int(d['id']),d)
 if path=='/api/mc/job/cancel':return job_annuler(c,p,int(d['id']))
 if path=='/api/mc/job/test':return job_tester(c,p,int(d['id']),d)
 if path=='/api/mc/review':return review_creer(c,p,d)
 if path=='/api/mc/role':return role_creer(c,p,d)
 if path=='/api/mc/branch':return branche_creer(c,p,d)
 if path=='/api/mc/branch/update':return branche_modifier(c,p,d)
 if path=='/api/mc/agent/clone':return agent_clone(c,p,d)
 if path=='/api/mc/agent/archive':return agent_archiver(c,p,d)
 if path=='/api/mc/recruit':return recrue_creer(c,p,d)
 if path=='/api/mc/recruit/decide':return recrue_decider(c,p,d)
 if path=='/api/mc/permissions':return permissions_definir(c,p,d)
 if path=='/api/mc/settings':return reglage_definir(c,p,d)
 if path=='/api/mc/backup':return {'file':sauvegarder().name}
 if path=='/api/mc/restore':return restaurer_sauvegarde(c,p,d)
 if path=='/api/mc/shutdown':return demander_arret()
 if path=='/api/mc/job/validate':return job_valider(c,p,d)
 if path=='/api/mc/job/commit':return job_commit(c,p,d)
 if path=='/api/mc/plan':return plan_proposer(c,p,d)
 if path=='/api/mc/plan/apply':return plan_appliquer(c,p,d)
 if path=='/api/mc/orchestrator/run':return orchestrateur_lancer(c,p,d)
 if path=='/api/mc/charge':return charge_agents(c,p)
 raise ValueError('Action inconnue')
def dispatch(c,path,d,principal=None):
 identity=principal if principal is not None else mc_security.current()
 with mc_security.use(identity):
  mc_security.authorize_route(c,path,d)
  return _dispatch(c,path,d)

def _guard_function(function,action,job_arg=False,payload_arg=None):
 signature=inspect.signature(function)
 names=list(signature.parameters)[2:]
 @functools.wraps(function)
 def guarded(c,p,*args,**kwargs):
  bound=signature.bind(c,p,*args,**kwargs);bound.apply_defaults()
  data=bound.arguments.get(names[payload_arg],{}) if payload_arg is not None else {}
  data=data or {}
  job=bound.arguments.get(names[0]) if job_arg else None
  if action in ('validate','commit','review'):job=data.get('job_id') or data.get('id')
  mc_security.require(c,p,action,data,job)
  return function(c,p,*args,**kwargs)
 return guarded

# Direct Python calls are privileged broker entry points too, not bypasses.
for _name,_action,_job,_payload in (
 ('job_creer','job_create',False,0),('job_lancer','job_run',True,None),
 ('job_pause','job_control',True,None),('job_reprendre','job_control',True,None),
 ('job_annuler','job_control',True,None),('job_refuser','approve',True,1),
 ('job_approuver','approve',True,1),('job_tester','test',True,1),
 ('job_valider','validate',False,0),('job_commit','commit',False,0),
 ('review_creer','review',False,0),('permissions_definir','admin',False,0),
 ('reglage_definir','admin',False,0),('restaurer_sauvegarde','admin',False,0),
 ('role_creer','admin',False,0),('recrue_decider','admin',False,0),
 ('agent_clone','manage',False,0),('agent_archiver','manage',False,0),
 ('branche_creer','manage',False,0),('branche_modifier','manage',False,0),
 ('plan_proposer','manage',False,0),('plan_appliquer','manage',False,0),
 ('orchestrateur_lancer','manage',False,0),('recrue_creer','manage',False,0)):
 globals()[_name]=_guard_function(globals()[_name],_action,_job,_payload)

class Handler(legacy.Handler):
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
   if maintenant-_fenetre[0]>=60:_fenetre[0]=maintenant;_fenetre[1]=0
   if _fenetre[1]>=LIMITE:return False
   _fenetre[1]+=1;return True
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
   html=(ROOT/'BM318d-Railway.html').read_text(encoding='utf-8')
   html=html.replace('</head>','<meta name="mc-token" content="'+TOKEN+'"><link rel="stylesheet" href="/mission.css"></head>')
   html=html.replace('</body>','<script src="/mission.js"></script><script src="/security-ui.js"></script><script src="/connectors.js"></script></body>')
   b=html.encode()
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
   self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
   self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
   self.send_header('Set-Cookie','mc_token='+TOKEN+'; Path=/; HttpOnly; SameSite=Strict')
   self.end_headers();self.wfile.write(b);return
  if self.path in ('/mission.js','/mission.css','/connectors.js','/security-ui.js'):
   path=ROOT/self.path[1:];b=path.read_bytes()
   self.send_response(200);self.send_header('Content-Type','text/javascript' if self.path.endswith('.js') else 'text/css')
   self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
   self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(b);return
  if self.path.startswith('/api/'):
   if not self._api_autorisee():return
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
   super().do_GET();return
  super().do_GET()
 def do_POST(self):
  if not (self.path.startswith('/api/') or self.path=='/event'):return super().do_POST()
  # Le corps est lu avant tout refus : sinon la fermeture de la connexion avec
  # des octets non lus fait perdre la reponse au client (RST sous Windows).
  try:n=int(self.headers.get('Content-Length','0'))
  except ValueError:n=0
  if n<0 or n>16000:
   self.close_connection=True;return self._refus(400,'Taille invalide')
  corps=self.rfile.read(n) if n else b''
  if not self._api_autorisee():return
  if not self._limite_ok():return self._refus(429,'Trop de requêtes : patientez une minute')
  if self.path in ('/api/mc/restore','/api/mc/settings','/api/mc/shutdown'):
   if not secrets.compare_digest(self.headers.get('X-MC-Admin') or '',ADMIN_TOKEN):
    return self._refus(403,'Jeton administrateur requis')
  if 'application/json' not in (self.headers.get('Content-Type') or '').lower():
   return self._refus(415,'Content-Type application/json requis')
  if not self.path.startswith('/api/mc/'):
   # Anciennes routes (/api/task, /api/event...) : le corps a deja ete lu, on le
   # remet a disposition du gestionnaire historique.
   import io
   if self.principal.kind=='agent':return self._refus(403,'Route historique non autorisée aux agents')
   self.rfile=io.BytesIO(corps)
   return super().do_POST()
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
  except (ValueError,KeyError,TypeError,sqlite3.Error) as e:self.reply({'error':str(e)},400)
if __name__=='__main__':
 import sys
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
 print('BM318d Mission Control '+adresse+' (jeton de session actif)',flush=True)
 SERVEUR[0].serve_forever()
