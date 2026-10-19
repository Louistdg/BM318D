"""Reglages de projet, recherche, notifications et historique.

Extrait de MissionControl.py. Les aides du serveur sont liees par `lier()`.
"""
import json
import os
from pathlib import Path

import mc_agent
from mc_actions import action

_lie = False


def lier(hote):
    global _lie
    if _lie:
        return
    globaux = globals()
    for nom in ('rows', 'one', 'audit', 'required_text', 'REGLAGES_DEFAUT', 'ROLES', 'STATUSES', 'REGLAGES_DEFAUT'):
        globaux[nom] = getattr(hote, nom)
    _lie = True



def reglages(c,p):
 valeurs=dict(REGLAGES_DEFAUT)
 valeurs['workspace_dir']=str(mc_agent.WORKSPACES)
 for ligne in rows(c,'SELECT key,value FROM mc_settings WHERE project_id=?',(p,)):valeurs[ligne['key']]=ligne['value']
 return valeurs

@action('admin',payload_arg=0)
def reglage_definir(c,p,d):
 cle=required_text(d,'key',40)
 if cle not in REGLAGES_DEFAUT:raise ValueError('Réglage inconnu : '+cle)
 valeur=str(d.get('value','')).strip()[:1024]
 if cle=='workspace_dir':
  if not valeur:raise ValueError('Le dossier des workspaces ne peut pas être vide')
  cible=Path(valeur).expanduser()
  if not cible.is_absolute():raise ValueError('Le dossier des workspaces doit être un chemin absolu')
  if os.name=='nt' and (not cible.drive or cible.drive.rstrip(':').upper() not in ('C','D')):
   raise ValueError('Choisis un dossier sur le disque C: ou D:')
  if os.name=='nt' and len(cible.parts)<2:raise ValueError('Choisis un sous-dossier sur C: ou D:, pas la racine du disque')
  cible.mkdir(parents=True,exist_ok=True)
  if not cible.is_dir():raise ValueError('Le chemin choisi n’est pas un dossier')
  valeur=str(cible.resolve())
 c.execute('INSERT INTO mc_settings(project_id,key,value) VALUES(?,?,?) ON CONFLICT(project_id,key) DO UPDATE SET value=excluded.value',(p,cle,valeur))
 if cle=='ollama_url' and valeur:mc_agent.OLLAMA=valeur
 if cle=='max_jobs':os.environ['MC_MAX_JOBS']=valeur
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

