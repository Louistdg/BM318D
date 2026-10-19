"""Agents, equipes, roles, permissions, branches, recrutement et plans.

Extrait de MissionControl.py. Les aides du serveur sont liees une fois par
`lier()`, appele par le module hote apres la definition de ses constantes.
"""
import datetime
import json

import mc_agent
import mc_plan
import mc_security
from mc_actions import action

_lie = False


def lier(hote):
    global _lie
    if _lie:
        return
    globaux = globals()
    for nom in ('ROLES', 'STATUSES', 'TOKEN', 'ROOT', 'agent', 'project', 'one', 'rows', 'audit',
                'required_text', 'journal', 'hierarchy_cycle', 'context_packet', 'snapshot',
                'mc_jobs', 'os', 're', 'secrets', 'sys'):
        globaux[nom] = getattr(hote, nom)
    _lie = True



def roles_projet(c,p):
 perso=rows(c,'SELECT key,label,description FROM mc_roles WHERE project_id=? ORDER BY key',(p,))
 base=[{'key':k,'label':k.capitalize(),'description':'','builtin':True} for k in ROLES]
 return base+[dict(r,builtin=False) for r in perso]

def role_valide(c,p,role):
 return any(r['key']==role for r in roles_projet(c,p))

@action('admin',payload_arg=0)
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

@action('admin',payload_arg=0)
def permissions_definir(c,p,d):
 equipe=required_text(d,'team',80)
 c.execute('INSERT INTO mc_team_permissions(project_id,team,can_create_agents,can_approve_jobs,can_run_tests) VALUES(?,?,?,?,?) ON CONFLICT(project_id,team) DO UPDATE SET can_create_agents=excluded.can_create_agents,can_approve_jobs=excluded.can_approve_jobs,can_run_tests=excluded.can_run_tests',(p,equipe,int(bool(d.get('can_create_agents',True))),int(bool(d.get('can_approve_jobs',True))),int(bool(d.get('can_run_tests',True)))))
 audit(c,p,'team_permissions',{'team':equipe});return {'ok':True}

@action('manage',payload_arg=0)
def branche_creer(c,p,d):
 nom=required_text(d,'name',80)
 architecte=d.get('architect_id');architecte=int(architecte) if architecte not in ('',None) else None
 if architecte:agent(c,p,architecte)
 cur=c.execute('INSERT INTO mc_branches(project_id,name,architect_id,description) VALUES(?,?,?,?)',(p,nom,architecte,str(d.get('description',''))[:400]))
 audit(c,p,'branch_created',{'id':cur.lastrowid,'name':nom});return {'id':cur.lastrowid}

@action('manage',payload_arg=0)
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

@action('manage',payload_arg=0)
def agent_clone(c,p,d):
 source=agent(c,p,int(d['id']))
 nom=str(d.get('name') or (source['name']+' (copie)'))[:100]
 cur=c.execute('INSERT INTO mc_agents(project_id,name,role,team,manager_id,status,model,instructions,x,y) VALUES(?,?,?,?,?,?,?,?,?,?)',(p,nom,source['role'],source['team'],source['manager_id'],'idle',source['model'],source['instructions'],source['x']+60,source['y']+60))
 audit(c,p,'agent_cloned',{'source':source['id'],'id':cur.lastrowid});return {'id':cur.lastrowid,'name':nom}

@action('manage',payload_arg=0)
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

@action('admin',payload_arg=0)
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

@action('manage',payload_arg=0)
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

@action('manage',payload_arg=0)
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

@action('manage',payload_arg=0)
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

@action('manage',payload_arg=0)
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

def agent_creer(c,p,d):
  name=required_text(d,'name',100);role=required_text(d,'role',40)
  if not role_valide(c,p,role):raise ValueError('Rôle inconnu')
  team=str(d.get('team','Général')).strip()[:80] or 'Général'
  manager=d.get('manager_id');manager=int(manager) if manager not in ('',None) else None
  if manager:agent(c,p,manager)
  cur=c.execute('INSERT INTO mc_agents(project_id,name,role,team,manager_id,x,y,instructions,skills) VALUES(?,?,?,?,?,?,?,?,?)',(p,name,role,team,manager,int(d.get('x',120)),int(d.get('y',120)),str(d.get('instructions',''))[:2000],str(d.get('skills',''))[:300]))
  c.execute('INSERT OR IGNORE INTO mc_team_permissions(project_id,team) VALUES(?,?)',(p,team))
  audit(c,p,'agent_created',{'id':cur.lastrowid,'name':name});return {'id':cur.lastrowid}

def agent_modifier(c,p,d):
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
