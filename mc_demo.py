"""Mode demonstration de TREDIO.

Cree un projet complet et coherent : trois agents, une mission, une affectation,
un job reellement execute (proposition, diff, ecriture, compilation verifiee),
une revue, une note de decision et les traces d'audit.

Aucune valeur inventee : la preuve enregistree est le resultat observe de la
compilation du fichier ecrit. Si la verification echoue, tout est annule.

Usage :
    python mc_demo.py                 cree la demonstration dans la base courante
    python mc_demo.py --force         la recree si elle existe deja
    python MissionControl.py --demo   idem, depuis le lanceur principal
"""
import datetime
import json
import py_compile
import shutil
import sqlite3
import time
from pathlib import Path

import mc_agent

NOM_PROJET = 'Démo — suivi de chantier'

AGENTS = [
    ('Camille', 'chef de projet', 'direction', 'qwen2.5:3b', 'Découpe le travail, arbitre les décisions.'),
    ('Yanis', 'développeur', 'livraison', 'qwen2.5:3b', 'Écrit le code, propose, ne valide jamais seul.'),
    ('Nour', 'relectrice', 'qualité', 'qwen2.5:3b', 'Cherche ce qui casse, relit les propositions.'),
]

MISSION = ('Livrer l’export CSV du module export',
           'Le fichier export.csv doit sortir sans colonne entièrement vide, et la sortie doit compiler.')

TACHE = ('Écrire la fonction export_csv du module export, sans colonne vide.',
         'Fonction export_csv avec filtrage des colonnes vides.')

CONTENU = '''def export_csv(lignes, chemins=None):
    """Écrit les lignes en CSV, sans colonne entièrement vide."""
    import csv
    colonnes = chemins or (list(lignes[0].keys()) if lignes else [])
    colonnes = [k for k in colonnes if any(str(r.get(k, "")).strip() for r in lignes)]
    with open("export.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=colonnes, extrasaction="ignore")
        w.writeheader()
        w.writerows(lignes)
'''


def _projet(c, nom):
    ligne = c.execute('SELECT id FROM projects WHERE name=?', (nom,)).fetchone()
    return ligne[0] if ligne else None


def _creer_projet(c, nom):
    return c.execute('INSERT INTO projects(name) VALUES(?)', (nom,)).lastrowid


def creer(c, nom_projet=NOM_PROJET, forcer=False):
    """Cree la demonstration. Rend un resume ; ne cree pas de doublon."""
    existant = _projet(c, nom_projet)
    if existant and not forcer:
        return {'cree': False, 'project_id': existant, 'raison': 'démonstration déjà présente'}
    if existant and forcer:
        _effacer(c, existant)

    p = _creer_projet(c, nom_projet)
    agents = []
    for nom, role, equipe, modele, consigne in AGENTS:
        ident = c.execute(
            'INSERT INTO mc_agents(project_id,name,role,team,status,model,instructions,x,y) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            (p, nom, role, equipe, 'disponible', modele, consigne, 120 + 180 * len(agents), 160)).lastrowid
        agents.append(ident)

    mission = c.execute('INSERT INTO mc_missions(project_id,title,objective,status) VALUES(?,?,?,?)',
                        (p, MISSION[0], MISSION[1], 'en cours')).lastrowid
    affectation = c.execute(
        'INSERT INTO mc_assignments(mission_id,agent_id,task,status) VALUES(?,?,?,?)',
        (mission, agents[1], TACHE[0], 'en cours')).lastrowid

    job = c.execute(
        'INSERT INTO mc_jobs(project_id,agent_id,mission_id,assignment_id,title,task,model) '
        'VALUES(?,?,?,?,?,?,?)',
        (p, agents[1], mission, affectation, 'export_csv.py propre', TACHE[0], 'qwen2.5:3b')).lastrowid
    racine = mc_agent.racine_workspace(p, agents[1], job)
    c.execute('UPDATE mc_jobs SET workspace=? WHERE id=?', (str(racine), job))

    proposition = {'summary': TACHE[1], 'files': [{'path': 'export_csv.py', 'content': CONTENU}]}
    fichiers = mc_agent.valider_proposition(racine, proposition)
    difference = mc_agent.diff(racine, fichiers)
    mc_agent.appliquer(racine, fichiers)

    # Verification reelle : on compile le fichier ecrit, la preuve est le resultat observe.
    debut = time.monotonic()
    try:
        py_compile.compile(str(racine / 'export_csv.py'), doraise=True)
    except Exception as erreur:
        # Un echec ne doit jamais produire une demonstration mensongere : tout est annule.
        try:
            (racine / 'export_csv.py').unlink(missing_ok=True)
            shutil.rmtree(racine / '__pycache__', ignore_errors=True)
            racine.rmdir()
        except OSError:
            pass
        raise ValueError('Démonstration refusée : la vérification de compilation a échoué — ' + str(erreur)) from erreur

    preuve = {
        'command': 'python -m py_compile export_csv.py',
        'exit_code': 0,
        'stdout': '',
        'stderr': '',
        'duration_ms': int((time.monotonic() - debut) * 1000),
        'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'job_id': job,
    }
    c.execute("UPDATE mc_jobs SET status='approved',proposal=?,diff=?,evidence=? WHERE id=?",
              (json.dumps(proposition, ensure_ascii=False), difference,
               json.dumps(preuve, ensure_ascii=False), job))
    c.execute("UPDATE mc_assignments SET status='done',result=?,verification='test',evidence=?,verified=1 "
              "WHERE id=?",
              (json.dumps({'livre': 'export_csv.py'}, ensure_ascii=False),
               json.dumps(preuve, ensure_ascii=False), affectation))

    revue = c.execute(
        'INSERT INTO mc_reviews(project_id,job_id,agent_id,kind,verdict,findings) VALUES(?,?,?,?,?,?)',
        (p, job, agents[2], 'relecture', 'ok',
         'Colonnes vides filtrées, fichier compilé, aucune écriture hors du workspace.')).lastrowid

    note = c.execute(
        'INSERT INTO mc_notes(project_id,agent_id,scope,content,team) VALUES(?,?,?,?,?)',
        (p, agents[0], 'décision',
         'Les colonnes entièrement vides ne sont pas exportées : décision validée après relecture. '
         'Un export vide reste un export valide, il ne doit pas produire de colonne fantôme.',
         'direction')).lastrowid

    c.execute('INSERT INTO mc_audit(project_id,action,details) VALUES(?,?,?)',
              (p, 'demo_creee', json.dumps({'job': job, 'mission': mission, 'agents': agents,
                                            'preuve': preuve['command']}, ensure_ascii=False)))
    return {'cree': True, 'project_id': p, 'agents': agents, 'mission': mission,
            'assignment': affectation, 'job': job, 'review': revue, 'note': note,
            'workspace': str(racine), 'evidence': preuve}


def _effacer(c, projet):
    """Supprime la demonstration dans l'ordre des dependances."""
    for table in ('mc_reviews', 'mc_notes', 'mc_documents', 'mc_jobs', 'mc_audit'):
        try:
            c.execute('DELETE FROM %s WHERE project_id=?' % table, (projet,))
        except sqlite3.OperationalError:
            continue
    c.execute('DELETE FROM mc_assignments WHERE mission_id IN '
              '(SELECT id FROM mc_missions WHERE project_id=?)', (projet,))
    c.execute('DELETE FROM mc_missions WHERE project_id=?', (projet,))
    c.execute('DELETE FROM mc_agents WHERE project_id=?', (projet,))
    c.execute('DELETE FROM projects WHERE id=?', (projet,))


def main(argv=None):
    import argparse
    import os
    import sys

    parseur = argparse.ArgumentParser(description='Crée une démonstration TREDIO complète.')
    parseur.add_argument('--force', action='store_true', help='recrée la démonstration si elle existe')
    parseur.add_argument('--nom', default=NOM_PROJET, help='nom du projet de démonstration')
    options = parseur.parse_args(argv)

    import MissionControl as mc
    mc.init()
    with mc.connect() as c:
        resultat = creer(c, options.nom, options.force)
    if not resultat.get('cree'):
        print('Démonstration déjà présente : projet', resultat['project_id'], '(utiliser --force pour la refaire)')
        return 0
    print('Démonstration créée.')
    print('  projet     :', resultat['project_id'])
    print('  agents     :', ', '.join(str(a) for a in resultat['agents']))
    print('  mission    :', resultat['mission'])
    print('  job        :', resultat['job'], '(approuvé)')
    print('  revue      :', resultat['review'])
    print('  note       :', resultat['note'])
    print('  preuve     :', resultat['evidence']['command'], '→ code', resultat['evidence']['exit_code'])
    print('  workspace  :', resultat['workspace'])
    print()
    print('Ouvrir http://127.0.0.1:31880/ puis choisir le projet « %s ».' % options.nom)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
