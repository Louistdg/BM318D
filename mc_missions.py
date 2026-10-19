"""Domaine projet : missions, affectations, notes, decisions, messages, passations.

Ces branches vivaient en ligne dans `_dispatch`. Elles sont ici, avec les memes
validations et les memes traces d'audit. Les aides de la base (one, agent,
audit, required_text) restent dans MissionControl : elles sont importees au
moment de l'appel, ce qui evite un import circulaire a l'ouverture du module.
"""
import datetime
import json


def _mc():
    """Le module hote : MissionControl, ou __main__ quand le serveur est le script lance."""
    import sys
    principal = sys.modules.get('__main__')
    if principal is not None and hasattr(principal, 'required_text') and hasattr(principal, 'audit'):
        return principal
    import MissionControl
    return MissionControl


def mission_creer(c, p, d):
    m = _mc()
    titre = m.required_text(d, 'title', 160)
    objectif = m.required_text(d, 'objective', 5000)
    curseur = c.execute('INSERT INTO mc_missions(project_id,title,objective) VALUES(?,?,?)',
                        (p, titre, objectif))
    m.audit(c, p, 'mission_created', {'id': curseur.lastrowid})
    return {'id': curseur.lastrowid}


def affectation_creer(c, p, d):
    m = _mc()
    mission = m.one(c, 'SELECT * FROM mc_missions WHERE project_id=? AND id=?', (p, int(d['mission_id'])))
    agent = m.agent(c, p, int(d['agent_id']))
    tache = m.required_text(d, 'task', 2000)
    curseur = c.execute('INSERT INTO mc_assignments(mission_id,agent_id,task) VALUES(?,?,?)',
                        (mission['id'], agent['id'], tache))
    m.audit(c, p, 'assignment_created', {'id': curseur.lastrowid, 'agent': agent['id']})
    return {'id': curseur.lastrowid}


def affectation_modifier(c, p, d):
    m = _mc()
    actuelle = m.one(c, 'SELECT a.* FROM mc_assignments a JOIN mc_missions m ON a.mission_id=m.id '
                        'WHERE a.id=? AND m.project_id=?', (int(d['id']), p))
    statut = d.get('status', actuelle['status'])
    if statut not in ('queued', 'working', 'blocked', 'done', 'reviewed'):
        raise ValueError('Statut invalide')
    resultat = str(d.get('result', actuelle['result']))[:8000]
    # Trois niveaux distincts, et une preuve obligatoire pour le troisieme :
    # declared = on affirme ; human = un humain a relu ; test = une commande a
    # reellement tourne, avec son code de sortie.
    verification = actuelle['verification']
    if 'verification' in d:
        verification = str(d['verification'])
    elif d.get('verified') is True:
        verification = 'human' if statut == 'reviewed' else actuelle['verification']
    if verification not in ('none', 'declared', 'human', 'test', 'approved', 'validated'):
        raise ValueError('Niveau de vérification inconnu')
    if verification in ('validated', 'approved'):
        raise ValueError('Validation refusée : seul le serveur peut valider après un test exécuté et des revues')
    if verification in ('human', 'test', 'approved', 'validated') and statut not in ('done', 'reviewed'):
        raise ValueError('On ne vérifie pas un travail encore en cours')
    preuve = actuelle['evidence']
    if verification == 'test':
        if 'evidence' not in d or not isinstance(d['evidence'], dict):
            raise ValueError('Preuve invalide')
        fournie = d['evidence']
        if not str(fournie.get('command', '')).strip() or not isinstance(fournie.get('exit_code'), int):
            raise ValueError('Preuve de test incomplète : commande et code de sortie (entier) requis')
        identifiant = fournie.get('job_id')
        if not isinstance(identifiant, int):
            raise ValueError('Preuve refusée : elle doit citer le job (job_id) qui l’a produite')
        job = m.one(c, 'SELECT * FROM mc_jobs WHERE project_id=? AND id=?', (p, identifiant))
        if job['status'] not in ('approved', 'completed'):
            raise ValueError('Preuve refusée : le job ' + str(identifiant) + ' n’est pas appliqué')
        if job['assignment_id'] not in (None, actuelle['id']):
            raise ValueError('Preuve refusée : elle appartient à une autre attribution')
        try:
            stockee = json.loads(job['evidence'] or '{}')
        except ValueError:
            stockee = {}
        if (stockee.get('command') != fournie.get('command')
                or stockee.get('exit_code') != fournie.get('exit_code')
                or stockee.get('job_id') != identifiant):
            raise ValueError('Preuve refusée : commande ou code de sortie différent du test exécuté')
        if len(job['evidence']) > 8000:
            raise ValueError('Preuve exécutée trop volumineuse')
        preuve = job['evidence']
    elif 'evidence' in d:
        if not isinstance(d['evidence'], dict):
            raise ValueError('Preuve invalide')
        preuve = json.dumps(d['evidence'], ensure_ascii=False)[:8000]
    verifie = 1 if verification in ('human', 'test') else 0
    verifie_le = (datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
                  if verifie else actuelle['verified_at'])
    verifie_par = m.auteur_preuve() if verifie else None
    c.execute('UPDATE mc_assignments SET status=?,result=?,verified=?,verification=?,evidence=?,'
              'verified_at=?,verified_by=? WHERE id=?',
              (statut, resultat, verifie, verification, preuve, verifie_le, verifie_par, actuelle['id']))
    m.audit(c, p, 'assignment_updated',
            {'id': actuelle['id'], 'status': statut, 'verification': verification, 'verified': verifie})
    return {'ok': True, 'verification': verification}


def note_creer(c, p, d):
    m = _mc()
    agent_id = d.get('agent_id')
    agent_id = int(agent_id) if agent_id not in ('', None) else None
    if agent_id:
        m.agent(c, p, agent_id)
    portee = d.get('scope', 'project')
    if portee not in ('project', 'team', 'agent'):
        raise ValueError('Portée invalide')
    equipe = str(d.get('team') or '').strip()[:80] or None
    if portee == 'team' and not equipe and agent_id:
        equipe = m.agent(c, p, agent_id)['team']
    if portee == 'team' and not equipe:
        raise ValueError('Une note d’équipe demande une équipe')
    remplace = d.get('supersedes')
    remplace = int(remplace) if remplace not in ('', None) else None
    if remplace is not None:
        ancienne = m.one(c, 'SELECT * FROM mc_notes WHERE project_id=? AND id=?', (p, remplace))
        if ancienne['scope'] != portee:
            raise ValueError('On ne remplace pas une note d’une autre portée')
        if portee == 'agent' and ancienne['agent_id'] != agent_id:
            raise m.mc_security.Refus('On ne remplace pas la note privée d’un autre agent')
        if portee == 'team' and ancienne['team'] != equipe:
            raise m.mc_security.Refus('On ne remplace pas la note d’une autre équipe')
    contenu = m.required_text(d, 'content', 4000)
    curseur = c.execute('INSERT INTO mc_notes(project_id,agent_id,scope,team,supersedes,content) '
                        'VALUES(?,?,?,?,?,?)', (p, agent_id, portee, equipe, remplace, contenu))
    m.audit(c, p, 'note_created', {'id': curseur.lastrowid, 'scope': portee, 'remplace': remplace})
    return {'id': curseur.lastrowid}


def decision_creer(c, p, d):
    m = _mc()
    agent_id = d.get('agent_id')
    agent_id = int(agent_id) if agent_id not in ('', None) else None
    if agent_id:
        m.agent(c, p, agent_id)
    titre = m.required_text(d, 'title', 160)
    decision = m.required_text(d, 'decision', 4000)
    raison = m.required_text(d, 'rationale', 4000)
    alternative = str(d.get('alternatives', ''))[:4000]
    curseur = c.execute('INSERT INTO mc_decisions(project_id,agent_id,title,decision,rationale,alternatives) '
                        'VALUES(?,?,?,?,?,?)', (p, agent_id, titre, decision, raison, alternative))
    m.audit(c, p, 'decision_recorded', {'id': curseur.lastrowid, 'title': titre})
    return {'id': curseur.lastrowid}


def message_envoyer(c, p, d):
    m = _mc()
    de = d.get('from_agent')
    de = int(de) if de not in ('', None) else None
    vers = d.get('to_agent')
    vers = int(vers) if vers not in ('', None) else None
    equipe = str(d.get('to_team') or '').strip()[:80] or None
    if de:
        m.agent(c, p, de)
    if vers:
        m.agent(c, p, vers)
    if bool(vers) == bool(equipe):
        raise ValueError('Un message vise un agent ou une équipe, pas les deux ni aucun')
    corps = m.required_text(d, 'body', 4000)
    curseur = c.execute('INSERT INTO mc_messages(project_id,from_agent,to_agent,to_team,body) '
                        'VALUES(?,?,?,?,?)', (p, de, vers, equipe, corps))
    m.audit(c, p, 'message_sent', {'id': curseur.lastrowid, 'vers_agent': vers, 'vers_equipe': equipe})
    return {'id': curseur.lastrowid}


def message_lire(c, p, d):
    m = _mc()
    message = m.one(c, 'SELECT * FROM mc_messages WHERE project_id=? AND id=?', (p, int(d['id'])))
    agent_id = int(d['agent_id'])
    agent = m.agent(c, p, agent_id)
    if not (message['to_agent'] == agent_id
            or (message['to_team'] and message['to_team'] == agent['team'])):
        raise ValueError('Ce message ne te concerne pas')
    if not message['read_at']:
        c.execute('UPDATE mc_messages SET read_at=CURRENT_TIMESTAMP WHERE id=?', (message['id'],))
        m.audit(c, p, 'message_read', {'id': message['id'], 'agent': agent_id})
    return {'ok': True, 'deja_lu': bool(message['read_at'])}


def handoff_ack(c, p, d):
    m = _mc()
    passation = m.one(c, 'SELECT * FROM mc_handoffs WHERE project_id=? AND id=?', (p, int(d['id'])))
    agent_id = int(d['agent_id'])
    m.agent(c, p, agent_id)
    if passation['new_manager_id'] != agent_id:
        raise ValueError('Seul le nouveau responsable peut acquitter cette passation')
    if passation['ack_at']:
        raise ValueError('Passation déjà acquittée')
    c.execute('UPDATE mc_handoffs SET ack_at=CURRENT_TIMESTAMP,ack_by=? WHERE id=?',
              (agent_id, passation['id']))
    m.audit(c, p, 'handoff_acknowledged', {'id': passation['id'], 'agent': agent_id})
    return {'ok': True}


def lien_creer(c, p, d):
    m = _mc()
    source = int(d['source_id'])
    cible = int(d['target_id'])
    genre = m.required_text(d, 'kind', 30)
    if source == cible or genre not in ('communication', 'dependency'):
        raise ValueError('Lien invalide')
    m.agent(c, p, source)
    m.agent(c, p, cible)
    if genre == 'dependency':
        graphe = {}
        for ligne in m.rows(c, "SELECT source_id,target_id FROM mc_links WHERE project_id=? AND kind='dependency'", (p,)):
            graphe.setdefault(ligne['source_id'], []).append(ligne['target_id'])
        a_voir = [cible]
        vus = set()
        while a_voir:
            noeud = a_voir.pop()
            if noeud == source:
                raise ValueError('Dépendance circulaire refusée')
            if noeud not in vus:
                vus.add(noeud)
                a_voir += graphe.get(noeud, [])
    c.execute('INSERT OR IGNORE INTO mc_links(project_id,source_id,target_id,kind) VALUES(?,?,?,?)',
              (p, source, cible, genre))
    m.audit(c, p, 'link_created', {'from': source, 'to': cible, 'kind': genre})
    return {'ok': True}
