"""BM318d — exécution contrôlée d'un job d'agent (P1).

Aucune commande arbitraire, aucune écriture hors d'un workspace dédié.
Ce module ne connaît ni HTTP ni SQLite : il reçoit une racine de workspace et
rend des résultats vérifiables (fichiers écrits, empreintes, code de sortie).
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

import mc_sandbox

RACINE = Path(__file__).resolve().parent
WORKSPACES = Path(os.environ.get('MC_WORKSPACES') or (RACINE / 'workspaces'))
TAILLE_MAX = 200_000          # octets par fichier proposé
FICHIERS_MAX = 20             # fichiers par proposition
DELAI_COMMANDE = 60           # secondes
DELAI_OLLAMA = int(os.environ.get('MC_OLLAMA_TIMEOUT') or 300)
BUDGET_OLLAMA = int(os.environ.get('MC_OLLAMA_BUDGET') or 600)
OLLAMA = 'http://127.0.0.1:11434/api/chat'

# Liste fermée. Une commande = un exécutable et des arguments fixes ; le seul
# paramètre accepté est un fichier du workspace, validé par chemin_sur().
COMMANDES = {
    'unittest': ('python', ['-m', 'unittest', '-v']),
    'py_compile': ('python', ['-m', 'py_compile']),
    'node_check': ('node', ['--check']),
}


class Refus(Exception):
    """Opération refusée par les règles de sécurité du workspace."""


def racine_workspace(projet, agent, job):
    base = (WORKSPACES / ('p%d' % projet) / ('a%d' % agent) / ('job%d' % job))
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def chemin_sur(racine, relatif):
    """Résout un chemin relatif en garantissant qu'il reste dans la racine."""
    if not isinstance(relatif, str) or not relatif.strip():
        raise Refus('Chemin vide ou invalide')
    if '\x00' in relatif:
        raise Refus('Chemin invalide')
    brut = Path(relatif)
    if brut.is_absolute() or relatif.startswith(('/', '\\')) or ':' in relatif:
        raise Refus('Chemin absolu refusé : ' + relatif)
    if any(part == '..' for part in brut.parts):
        raise Refus('Remontée de dossier refusée : ' + relatif)
    cible = (racine / brut).resolve()
    if cible != racine and racine not in cible.parents:
        raise Refus('Chemin hors du workspace refusé : ' + relatif)
    return cible


def valider_proposition(racine, proposition):
    """Contrôle la forme de la proposition avant tout affichage ou écriture."""
    if not isinstance(proposition, dict):
        raise Refus('Proposition illisible : objet JSON attendu')
    fichiers = proposition.get('files')
    if not isinstance(fichiers, list) or not fichiers:
        raise Refus('Aucun fichier proposé')
    if len(fichiers) > FICHIERS_MAX:
        raise Refus('Trop de fichiers proposés (%d)' % len(fichiers))
    valides = []
    for entree in fichiers:
        if not isinstance(entree, dict):
            raise Refus('Fichier proposé illisible')
        chemin = chemin_sur(racine, str(entree.get('path', '')))
        contenu = entree.get('content')
        if not isinstance(contenu, str):
            raise Refus('Contenu non textuel refusé : ' + str(entree.get('path')))
        if '\x00' in contenu:
            raise Refus('Contenu binaire refusé : ' + str(entree.get('path')))
        if len(contenu.encode('utf-8')) > TAILLE_MAX:
            raise Refus('Fichier trop gros : ' + str(entree.get('path')))
        valides.append((chemin, contenu))
    return valides


def proposition_depuis_texte(texte):
    """Extrait un objet JSON d'une réponse de modèle, même entourée de texte."""
    if isinstance(texte, dict):
        return texte
    brut = str(texte or '').strip()
    if not brut:
        raise Refus('Réponse vide du modèle')
    try:
        return json.loads(brut)
    except ValueError:
        pass
    debut, fin = brut.find('{'), brut.rfind('}')
    if debut >= 0 and fin > debut:
        try:
            return json.loads(brut[debut:fin + 1])
        except ValueError:
            pass
    raise Refus('Réponse du modèle sans objet JSON exploitable')


def diff(racine, fichiers):
    morceaux = []
    for chemin, contenu in fichiers:
        relatif = str(chemin.relative_to(racine))
        actuel = chemin.read_text(encoding='utf-8') if chemin.exists() else ''
        morceau = ''.join(difflib.unified_diff(
            actuel.splitlines(True), contenu.splitlines(True),
            fromfile=('a/' + relatif) if actuel else '/dev/null',
            tofile='b/' + relatif))
        if morceau:
            morceaux.append(morceau)
    return '\n'.join(morceaux)


def empreintes(racine, chemins):
    sortie = []
    for chemin in chemins:
        donnees = chemin.read_bytes() if chemin.exists() else b''
        sortie.append({'path': str(chemin.relative_to(racine)),
                       'bytes': len(donnees),
                       'sha256': hashlib.sha256(donnees).hexdigest()})
    return sortie


def appliquer(racine, fichiers):
    """Écrit les fichiers après approbation, par renommage atomique."""
    for chemin, contenu in fichiers:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = chemin.with_name(chemin.name + '.tmp-bm318d')
        temporaire.write_text(contenu, encoding='utf-8', newline='')
        os.replace(temporaire, chemin)
    return empreintes(racine, [c for c, _ in fichiers])


def executer_commande(racine, nom, fichier=None, delai=DELAI_COMMANDE):
    """Exécute une commande autorisée dans le bac à sable système (copie jetable)."""
    if nom not in COMMANDES:
        raise Refus('Commande non autorisée : ' + str(nom))
    executable, arguments = COMMANDES[nom]
    argv = [executable] + list(arguments)
    if fichier is not None:
        argv.append(str(chemin_sur(racine, fichier)))
    resultat = mc_sandbox.executer(argv, str(racine), delai=delai)
    return {'command': ' '.join(argv), 'exit_code': resultat['exit_code'],
            'stdout': resultat['stdout'], 'stderr': resultat['stderr'],
            'duration_ms': resultat['duration_ms'], 'timeout': resultat.get('timeout'),
            'isolement': resultat.get('isolement', {})}


def lire_contexte(racine, limite_fichiers=20, limite_octets=20000, par_fichier=4000):
    """Lit les fichiers texte du workspace pour que l'agent parte de l'existant.

    L'agent ne lit que son propre workspace : aucun chemin extérieur n'est ouvert.
    """
    # The broker must not ingest a linked secret into a model prompt before
    # the execution sandbox is reached. No untrusted process writes this tree.
    racine=Path(racine).absolute()
    if os.name=='nt':mc_sandbox.valider_workspace_windows(racine)
    else:
        from mc_sandbox_linux import valider_arbre
        valider_arbre(racine)
    extensions = {'.py', '.js', '.mjs', '.json', '.md', '.txt', '.css', '.html', '.ts'}
    morceaux, total = [], 0
    for chemin in sorted(racine.rglob('*')):
        if not chemin.is_file() or chemin.suffix.lower() not in extensions:
            continue
        try:
            with chemin.open('r',encoding='utf-8') as stream:texte=stream.read(par_fichier)
        except (UnicodeDecodeError, OSError):
            continue
        morceau = '--- ' + str(chemin.relative_to(racine)) + ' ---\n' + texte[:par_fichier]
        if total + len(morceau) > limite_octets:
            break
        morceaux.append(morceau)
        total += len(morceau)
        if len(morceaux) >= limite_fichiers:
            break
    return '\n\n'.join(morceaux)


def modeles_ollama(delai=5):
    """Liste les modèles réellement installés, pour ne pas en inventer un."""
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=delai) as reponse:
        donnees = json.load(reponse)
    return [m.get('name', '') for m in donnees.get('models', []) if m.get('name')]


def analyser_diff(diff):
    """Audit de sécurité déterministe sur un diff proposé.

    Ce n'est pas un antivirus : c'est une liste de motifs à risque connus, qui
    produit des constats vérifiables (fichier + ligne) plutôt qu'une impression.
    """
    motifs = [
        (r'\beval\s*\(', 'eval() exécute du code arbitraire'),
        (r'\bexec\s*\(', 'exec() exécute du code arbitraire'),
        (r'shell\s*=\s*True', 'subprocess avec shell=True'),
        (r'\bos\.system\s*\(', 'os.system lance une commande système'),
        (r'\bsubprocess\.(?:call|run|Popen)\s*\(', 'lancement de processus externe'),
        (r'(?<![\w.])__import__\s*\(', 'import dynamique'),
        (r'C:\\\\', 'chemin absolu Windows en dur'),
        (r'/etc/(?:passwd|shadow)', 'accès à un fichier système'),
        (r'\.\./\.\.', 'remontée de répertoires'),
        (r'requests\.(?:get|post)\s*\(\s*["\']http://', 'appel HTTP en clair'),
    ]
    constats = []
    fichier = ''
    numero = 0
    for ligne in (diff or '').splitlines():
        if ligne.startswith('+++ b/'):
            fichier = ligne[6:].strip()
            continue
        if ligne.startswith('@@'):
            try:
                numero = int(ligne.split('+')[1].split(',')[0].split(' ')[0])
            except (IndexError, ValueError):
                numero = 0
            continue
        if not ligne.startswith('+') or ligne.startswith('+++'):
            continue
        numero += 1
        for motif, explication in motifs:
            if re.search(motif, ligne):
                constats.append({'fichier': fichier, 'ligne': numero,
                                 'extrait': ligne[1:].strip()[:160],
                                 'probleme': explication})
    return constats


def commit_git(racine, message):
    """Git stays isolated too: hooks/filters cannot run on the Windows host."""
    return mc_sandbox.commit_git(racine,message)


def generer_ollama(modele, systeme, tache, contexte, delai=None, budget=None):
    """Un seul appel, non streamé, avec budget de tokens et délai bornés."""
    delai = delai or DELAI_OLLAMA
    budget = budget or BUDGET_OLLAMA
    messages = [{'role': 'system', 'content': systeme},
                {'role': 'user', 'content': tache + '\n\nContexte:\n' + contexte}]
    charge = json.dumps({'model': modele, 'stream': False, 'format': 'json',
                         # Les modeles de raisonnement consomment tout le budget
                         # dans « thinking » et rendent un contenu vide : on le
                         # coupe, sinon la reponse est inutilisable.
                         'think': str(os.environ.get('MC_OLLAMA_THINK') or '0') not in ('0', 'false', 'False'),
                         'messages': messages,
                         'options': {'num_predict': budget, 'temperature': 0.2}}).encode()
    requete = urllib.request.Request(OLLAMA, data=charge, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        donnees = json.load(reponse)
    return proposition_depuis_texte(donnees.get('message', {}).get('content', ''))


SYSTEME = (
    'Tu es un agent de développement dans un espace de travail isolé. '
    'Tu réponds UNIQUEMENT par un objet JSON valide, sans texte autour, de la forme '
    '{"summary": "une phrase", "files": [{"path": "chemin/relatif.py", "content": "contenu complet"}]}. '
    'Les chemins sont relatifs, sans "..", sans lettre de lecteur. '
    "N'invente aucun fichier existant : le contenu fourni remplace le fichier. "
    "N'ajoute aucune commande : les tests seront lancés par l'humain."
)
