"""Cycle de vie des jobs : proposition, execution, preuve, revue, validation.

Extrait de MissionControl.py. Les aides du serveur (connexion, audit, agents,
reglages, constantes) sont liees une fois par `lier()`, appele par le module
hote apres la definition de ses constantes.
"""
import datetime
import json
import re
import threading
from pathlib import Path

import mc_agent
import mc_security
from mc_actions import action

_lie = False


def lier(hote):
    """Recoit du serveur les aides dont ce module a besoin."""
    global _lie
    if _lie:
        return
    globaux = globals()
    for nom in ('LOCK', 'MAX_PREUVE', 'MAX_TEXTE', 'agent', 'audit', 'connect',
                'context_packet', 'journal', 'one', 'reglages', 'required_text', 'rows',
                '_verrous', '_pauses', '_annulations', 'acteur', 'contextvars', 'mc_connectors'):
        globaux[nom] = getattr(hote, nom)
    _lie = True


def job_publie(c,p,i):
 return one(c,'SELECT * FROM mc_jobs WHERE project_id=? AND id=?',(p,i))

@action('job_create',payload_arg=0)
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
 racine=mc_agent.racine_workspace(p,a['id'],job,reglages(c,p).get('workspace_dir'))
 c.execute('UPDATE mc_jobs SET workspace=? WHERE id=?',(str(racine),job))
 journal(c,job,'créé · agent %s · modèle %s'%(a['name'],modele))
 audit(c,p,'job_created',{'id':job,'agent':a['id'],'title':titre})
 return {'id':job,'workspace':str(racine),'model':modele}

@action('job_run',job_arg=True)
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

@action('job_control',job_arg=True)
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

@action('job_control',job_arg=True)
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

@action('approve',job_arg=True,payload_arg=1)
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

@action('approve',job_arg=True,payload_arg=1)
def job_refuser(c,p,i,d):
 j=job_publie(c,p,i)
 if j['status'] not in ('proposed','paused'):raise ValueError('On ne refuse pas un travail déjà appliqué ('+j['status']+') : utilisez git ou la restauration')
 motif=str(d.get('reason','Refusé par un humain'))[:500]
 c.execute("UPDATE mc_jobs SET status='cancelled',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",(motif,i))
 journal(c,i,'refusé : '+motif[:200])
 audit(c,p,'job_rejected',{'id':i,'raison':motif[:300]})
 return {'ok':True}

@action('job_control',job_arg=True)
def job_annuler(c,p,i):
 j=job_publie(c,p,i)
 if j['status'] in ('approved','completed'):raise ValueError('Job déjà appliqué : on ne l’annule plus')
 _annulations.add(i);_pauses.discard(i)
 c.execute("UPDATE mc_jobs SET status='cancelled',finished_at=CURRENT_TIMESTAMP WHERE id=?",(i,))
 journal(c,i,'annulé par un humain')
 audit(c,p,'job_cancelled',{'id':i})
 return {'ok':True}

def auteur_preuve():
 """Principal authentifié, jamais le nom envoyé par le client."""
 identite=mc_security.current()
 if identite.kind=='agent' and identite.agent:return 'agent:%d'%identite.agent
 return identite.kind

@action('test',job_arg=True,payload_arg=1)
def job_tester(c,p,i,d):
 acteur(c,p,d,'can_run_tests')
 j=job_publie(c,p,i)
 if j['status'] not in ('approved','completed'):
  raise ValueError('On ne teste pas un travail non appliqué (statut '+j['status']+')')
 if not j['workspace']:raise ValueError('Workspace absent')
 racine=Path(j['workspace'])
 commande=required_text(d,'command',40)
 fichier=d.get('file')
 if commande in ('py_compile','node_check'):
  fichier=required_text(d,'file',500)
  cible=mc_agent.chemin_sur(racine,fichier)
  if not cible.is_file():raise ValueError('Le fichier à vérifier doit exister dans le workspace')
 elif commande=='unittest':
  tests=list(racine.rglob('test*.py'))+list(racine.rglob('*_test.py'))
  if not tests:raise ValueError('Aucun fichier de test trouvé dans le workspace')
  if fichier is not None and mc_agent.chemin_sur(racine,fichier) not in tests:raise ValueError('Le fichier fourni n’est pas un fichier de test du workspace')
 resultat=mc_agent.executer_commande(racine,commande,fichier)
 if commande=='unittest' and resultat['exit_code']==0 and not re.search(r'Ran\s+[1-9]\d*\s+tests?',resultat.get('stdout','')+'\n'+resultat.get('stderr','')):
  resultat['exit_code']=2
  resultat['stderr']=(resultat.get('stderr','')+'\nAucun test exécuté : preuve refusée').strip()
 resultat['at']=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
 resultat['job_id']=j['id']
 preuve=json.dumps(resultat,ensure_ascii=False)
 if len(preuve)>MAX_PREUVE:raise ValueError('Preuve trop volumineuse (%d caractères, maximum %d)'%(len(preuve),MAX_PREUVE))
 c.execute('UPDATE mc_jobs SET evidence=? WHERE id=?',(preuve,i))
 statut='completed' if j['status']=='approved' and resultat['exit_code']==0 else j['status']
 if statut!=j['status']:c.execute("UPDATE mc_jobs SET status='completed' WHERE id=?",(i,))
 journal(c,i,'test %s → code %s (%s ms)'%(resultat['command'],resultat['exit_code'],resultat['duration_ms']))
 if j['assignment_id'] and resultat['exit_code']==0:
  c.execute("UPDATE mc_assignments SET verification='test',verified=1,evidence=?,verified_at=?,verified_by=? WHERE id=?",(preuve,resultat['at'],auteur_preuve(),j['assignment_id']))
 audit(c,p,'job_tested',{'id':i,'command':resultat['command'],'exit_code':resultat['exit_code']})
 return {'evidence':resultat,'status':statut}

# --- P5 : revue, validation, commit, rapport --------------------------------
@action('review',payload_arg=0)
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

@action('validate',payload_arg=0)
def job_valider(c,p,d):
 acteur(c,p,d,'can_approve_jobs')
 j=job_publie(c,p,int(d['id']))
 if j['status'] not in ('approved','completed'):raise ValueError('Seul un travail appliqué peut être validé')
 try:preuve=json.loads(j['evidence'] or '{}')
 except ValueError:preuve={}
 if preuve.get('exit_code')!=0:
  raise ValueError('Aucun test réussi enregistré : lance d’abord « Lancer les tests »')
 # A self-contained green test is not proof of a delivered change.
 # Only a proposed, non-test source file may unlock final validation.
 try:proposition=json.loads(j['proposal'] or '{}')
 except (ValueError,TypeError):proposition={}
 sources=[]
 for fichier in proposition.get('files',[]):
  if not isinstance(fichier,dict):continue
  chemin=Path(str(fichier.get('path') or ''))
  morceaux={part.lower() for part in chemin.parts}
  nom=chemin.stem.lower()
  if chemin.suffix.lower() not in ('.py','.js','.mjs','.jsx','.ts','.tsx','.html','.css','.sql'):continue
  if morceaux.intersection({'test','tests','__tests__'}) or nom.startswith('test_') or nom.endswith('_test'):continue
  if len(str(fichier.get('content') or '').strip())>=16:sources.append(str(chemin))
 if not sources:
  raise ValueError('Validation refusée : aucune source développée hors fichiers de tests dans la proposition')
 revues=rows(c,'SELECT kind,verdict,agent_id FROM mc_reviews WHERE job_id=?',(j['id'],))
 mauvaises=[r['kind'] for r in revues if r['verdict']!='ok']
 if mauvaises:raise ValueError('Revue(s) en échec : '+', '.join(mauvaises))
 if not any(r['kind'] in ('code','securite') for r in revues):raise ValueError('Aucune revue de code enregistrée')
 if not any(r['kind']=='tests' and r['agent_id'] is None for r in revues):raise ValueError('Une revue humaine des tests est requise avant validation')
 maintenant=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
 c.execute("UPDATE mc_jobs SET status='completed',finished_at=CURRENT_TIMESTAMP WHERE id=?",(j['id'],))
 journal(c,j['id'],'validé : tests verts et revues favorables')
 if j['assignment_id']:
  c.execute("UPDATE mc_assignments SET verification='validated',verified=1,evidence=?,verified_at=?,verified_by=? WHERE id=?",(j['evidence'],maintenant,auteur_preuve(),j['assignment_id']))
 audit(c,p,'job_validated',{'id':j['id'],'revues':[r['kind'] for r in revues]})
 return {'ok':True,'verification':'validated'}

@action('commit',payload_arg=0)
def job_commit(c,p,d):
 acteur(c,p,d,'can_approve_jobs')
 j=job_publie(c,p,int(d['id']))
 if j['status'] not in ('approved','completed'):raise ValueError('Seul un travail appliqué peut être commité')
 message=str(d.get('message') or ('TREDIO job %d : %s'%(j['id'],j['title'])))[:200]
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
