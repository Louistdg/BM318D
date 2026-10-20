"""Routes historiques de TREDIO, repliees dans le routeur normal.

Elles etaient servies par un second serveur HTTP (DIOPTRE-WebServer.py, port
31879, sans authentification) charge par importlib et herite par sous-classement.
Ce module ne contient plus que des fonctions : le serveur unique les appelle
apres avoir verifie le jeton, l'hote et l'origine.
"""
import json
import time
import urllib.request

OLLAMA = 'http://127.0.0.1:11434'
_CACHE = {'quand': 0.0, 'liste': []}


def _lignes(c, requete, args=()):
    return [tuple(r) for r in c.execute(requete, args).fetchall()]


def _projet(c, projet):
    return c.execute('SELECT 1 FROM projects WHERE id=?', (int(projet),)).fetchone() is not None


def modeles_installes():
    """Liste des modeles Ollama, cache 10 secondes."""
    if time.time() - _CACHE['quand'] < 10:
        return _CACHE['liste']
    liste = []
    try:
        with urllib.request.urlopen(OLLAMA + '/api/tags', timeout=3) as reponse:
            liste = [m['name'] for m in json.load(reponse).get('models', [])]
    except Exception:
        liste = []
    _CACHE.update(quand=time.time(), liste=liste)
    return liste


def contexte_projet(c, projet):
    """Contexte factuel court, lu en base. Les zeros sont dits explicitement."""
    faits = ['Application: TREDIO Control Center (gestion de projet, agents IA locaux, securite V2.3)']

    def ajoute(texte):
        faits.append(texte)

    try:
        ligne = _lignes(c, 'SELECT name FROM projects WHERE id=?', (projet,))
        ajoute('Projet: ' + str(ligne[0][0]) + ' (id ' + str(projet) + ')' if ligne else 'Projet inconnu')
        ajoute('Agents: ' + str(c.execute('SELECT count(*) FROM mc_agents WHERE project_id=?', (projet,)).fetchone()[0]))
        noms = _lignes(c, 'SELECT name FROM mc_agents WHERE project_id=? ORDER BY id LIMIT 6', (projet,))
        if noms:
            ajoute('Noms des agents: ' + ', '.join(str(r[0]) for r in noms))
        for table, label in (('mc_missions', 'Missions'), ('tasks', 'Taches'), ('mc_connectors', 'Connecteurs')):
            n = c.execute('SELECT count(*) FROM ' + table + ' WHERE project_id=?', (projet,)).fetchone()[0]
            ajoute(label + ': ' + str(n))
        jobs = _lignes(c, 'SELECT status,count(*) FROM mc_jobs WHERE project_id=? GROUP BY status', (projet,))
        ajoute('Jobs: ' + (', '.join(str(r[0]) + ' ' + str(r[1]) for r in jobs) if jobs else 'aucun'))
        evenements = _lignes(c, 'SELECT agent,status,substr(message,1,120) FROM events WHERE project_id=? '
                                'ORDER BY id DESC LIMIT 3', (projet,))
        if evenements:
            ajoute('Derniers evenements: ' + ' | '.join(str(e[0]) + ' (' + str(e[1]) + '): ' + str(e[2]) for e in evenements))
        regle = _lignes(c, "SELECT value FROM mc_settings WHERE project_id=? AND key='ollama_model'", (projet,))
        if regle:
            ajoute('Modele configure: ' + str(regle[0][0]))
        ajoute('Securite: connecteurs proteges par jeton administrateur, execution de code en bac a sable, MCP verrouille')
    except Exception as erreur:
        ajoute('Contexte partiel (' + type(erreur).__name__ + ')')
    return '\n'.join('- ' + f for f in faits)


def modele_ollama(c, projet):
    """Modele Ollama : variable d'environnement, sinon reglage du projet, sinon defaut."""
    import os
    nom = os.environ.get('MC_OLLAMA_MODEL') or 'qwen2.5:3b'
    try:
        ligne = _lignes(c, "SELECT value FROM mc_settings WHERE project_id=? AND key='ollama_model'", (projet,))
        if ligne and ligne[0][0]:
            nom = str(ligne[0][0])
    except Exception:
        pass
    return nom


def etat(c):
    return {
        'projects': _lignes(c, 'SELECT id,name FROM projects ORDER BY id DESC'),
        'tasks': _lignes(c, 'SELECT id,project_id,title,priority,agent,status FROM tasks ORDER BY id'),
        'events': _lignes(c, 'SELECT id,project_id,created,agent,status,message FROM events ORDER BY id DESC LIMIT 300'),
        'edges': _lignes(c, 'SELECT task_id,depends_on FROM task_dependencies'),
        'positions': _lignes(c, 'SELECT project_id,task_id,x,y FROM canvas_positions'),
    }


def projet_creer(c, d):
    nom = str(d['name']).strip()[:120]
    if not nom:
        raise ValueError('Nom de projet invalide')
    return {'id': c.execute('INSERT INTO projects(name) VALUES(?)', (nom,)).lastrowid}


def tache_creer(c, d):
    projet = int(d['project'])
    titre = str(d['title']).strip()[:300]
    if not titre or not _projet(c, projet):
        raise ValueError('Projet ou titre invalide')
    ident = c.execute('INSERT INTO tasks(project_id,title,priority,agent) VALUES(?,?,?,?)',
                      (projet, titre, str(d.get('priority', 'Normale'))[:30], str(d.get('agent', 'IA 1'))[:80])).lastrowid
    return {'id': ident}


def tache_modifier(c, d):
    projet = int(d['project'])
    ident = int(d['id'])
    titre = str(d['title']).strip()
    if not titre or len(titre) > 300 or not c.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?',
                                                      (ident, projet)).fetchone():
        raise ValueError('Tâche introuvable ou titre invalide')
    c.execute('UPDATE tasks SET title=?,priority=?,agent=? WHERE id=? AND project_id=?',
              (titre, str(d['priority'])[:30], str(d['agent'])[:80], ident, projet))
    return {'id': ident}


def statut(c, d):
    c.execute('UPDATE tasks SET status=? WHERE id=? AND project_id=?',
              (str(d['status'])[:50], int(d['id']), int(d['project'])))
    return {'id': int(d['id'])}


def position(c, d):
    ident = int(d['id'])
    projet = int(d['project'])
    if not c.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?', (ident, projet)).fetchone():
        raise ValueError('Tâche introuvable')
    x = max(-10000, min(10000, int(d['x'])))
    y = max(-10000, min(10000, int(d['y'])))
    c.execute('INSERT INTO canvas_positions(project_id,task_id,x,y) VALUES(?,?,?,?) '
              'ON CONFLICT(task_id) DO UPDATE SET x=excluded.x,y=excluded.y', (projet, ident, x, y))
    return {'id': ident}


def lien(c, d):
    tache = int(d['task'])
    depend = int(d['depends_on'])
    projet = int(d['project'])
    valides = {r[0] for r in _lignes(c, 'SELECT id FROM tasks WHERE project_id=?', (projet,))}
    if tache == depend or tache not in valides or depend not in valides:
        raise ValueError('Tâches invalides')
    graphe = {}
    for a, b in _lignes(c, 'SELECT task_id,depends_on FROM task_dependencies'):
        graphe.setdefault(a, []).append(b)
    a_voir = [depend]
    vus = set()
    while a_voir:
        noeud = a_voir.pop()
        if noeud == tache:
            raise ValueError('Dépendance circulaire')
        if noeud in vus:
            continue
        vus.add(noeud)
        a_voir.extend(graphe.get(noeud, []))
    c.execute('INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)', (tache, depend))
    return {'id': tache}


def evenement(c, d):
    projet = int(d.get('project', d.get('project_id', 0)))
    agent = str(d['agent'])[:100]
    statut_ = str(d['status'])[:40]
    message = str(d['message']).strip()[:2000]
    if not message or not agent or statut_ not in ('working', 'blocked', 'done', 'idle') or not _projet(c, projet):
        raise ValueError('Événement invalide')
    return {'id': c.execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',
                            (projet, agent, statut_, message)).lastrowid}


def ollama(c, d):
    """Chat local. Le contexte projet est lu en base ; la reponse n'est jamais presentee comme verifiee."""
    projet = int(d['project'])
    prompt = str(d.get('prompt') or '').strip()
    if len(prompt) > 120000:
        raise ValueError('Prompt trop volumineux (120 000 caractères maximum)')
    if not prompt and not d.get('history'):
        raise ValueError('Prompt invalide : texte vide')
    if not _projet(c, projet):
        raise ValueError('Prompt invalide : projet inconnu')
    choisi = str(d.get('model') or '').strip()[:80]
    if choisi and choisi not in modeles_installes():
        raise ValueError('Modèle non installé : ' + choisi)
    c.execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',
              (projet, 'Ollama', 'working', 'Mission: ' + prompt[:1800]))
    try:
        messages = [{'role': 'system',
                     'content': 'Assistant de développement en lecture seule. Ne prétends pas avoir modifié des '
                                'fichiers ni exécuté des tests. Contexte réel du projet, seul fiable : '
                                + contexte_projet(c, projet) + '. Si une information demandée n est pas dans ce '
                                'contexte, dis clairement que tu ne sais pas.'}]
        historique = d.get('history')
        if historique is not None:
            if not isinstance(historique, list) or len(historique) > 12:
                raise ValueError('Historique de conversation invalide')
            total = 0
            for message in historique:
                if (not isinstance(message, dict) or message.get('role') not in ('user', 'assistant')
                        or not isinstance(message.get('content'), str)):
                    raise ValueError('Message historique invalide')
                contenu = message['content']
                total += len(contenu)
                if len(contenu) > 120000 or total > 120000:
                    raise ValueError('Historique de conversation trop volumineux')
                messages.append({'role': message['role'], 'content': contenu})
        else:
            messages.append({'role': 'user', 'content': prompt})
        charge = json.dumps({'model': choisi or modele_ollama(c, projet), 'keep_alive': '30m', 'stream': False,
                             'messages': messages, 'options': {'num_predict': 1200}}).encode()
        requete = urllib.request.Request(OLLAMA + '/api/chat', data=charge,
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(requete, timeout=120) as reponse:
            answer = json.load(reponse).get('message', {}).get('content', '').strip()
        if not answer:
            raise ValueError('Réponse vide')
        c.execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',
                  (projet, 'Ollama', 'done', ('Réponse non vérifiée: ' + answer)[:2000]))
        return {'ok': True, 'answer': answer}
    except Exception as erreur:
        c.execute('INSERT INTO events(project_id,agent,status,message) VALUES(?,?,?,?)',
                  (projet, 'Ollama', 'blocked', str(erreur)[:2000]))
        raise


ROUTES_POST = {
    '/api/project': projet_creer,
    '/api/task': tache_creer,
    '/api/task/update': tache_modifier,
    '/api/status': statut,
    '/api/position': position,
    '/api/link': lien,
    '/api/event': evenement,
    '/event': evenement,
    '/api/ollama': ollama,
}
