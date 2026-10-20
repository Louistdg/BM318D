"""TREDIO — P2 : planification multi-agents.

Décomposition d'un objectif en tâches (par un modèle, injectable pour les tests),
validation du graphe de dépendances, choix d'agent selon rôle et charge, et
mesure de la mémoire libre pour borner les exécutions simultanées.
"""
import ctypes
import os
import subprocess
import time

ROLES = ('manager', 'architect', 'frontend', 'backend', 'database', 'tester',
         'auditor', 'security', 'documentation', 'specialist')
MAX_TACHES = 8


class PlanInvalide(Exception):
    pass


def memoire_libre_mo():
    """Mémoire physique disponible, sans dépendance externe."""
    if hasattr(ctypes, 'windll'):
        class Etat(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        etat = Etat()
        etat.dwLength = ctypes.sizeof(Etat)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(etat)):
            return None
        return int(etat.ullAvailPhys / (1024 * 1024))
    try:
        with open('/proc/meminfo', encoding='ascii') as fichier:
            for ligne in fichier:
                if ligne.startswith('MemAvailable:'):
                    return int(ligne.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def cpu_charge(intervalle=0.2):
    """Charge CPU en pourcentage, mesurée sur un court intervalle (Windows)."""
    class Filetemps(ctypes.Structure):
        _fields_ = [('bas', ctypes.c_uint32), ('haut', ctypes.c_uint32)]

    def valeur(ft):
        return (ft.haut << 32) | ft.bas

    def lire():
        inactif, noyau, utilisateur = Filetemps(), Filetemps(), Filetemps()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(inactif), ctypes.byref(noyau), ctypes.byref(utilisateur)):
            raise OSError('GetSystemTimes a échoué')
        return valeur(inactif), valeur(noyau), valeur(utilisateur)

    try:
        i1, k1, u1 = lire()
        time.sleep(intervalle)
        i2, k2, u2 = lire()
    except (OSError, AttributeError):
        return None
    inactif = i2 - i1
    total = (k2 - k1) + (u2 - u1)
    if total <= 0:
        return None
    return round(100.0 * (1.0 - inactif / total), 1)


def gpu_info():
    """Utilisation GPU si nvidia-smi est disponible ; None sinon (pas d'invention)."""
    try:
        fait = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total',
                               '--format=csv,noheader,nounits'],
                              capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if fait.returncode != 0 or not fait.stdout.strip():
        return None
    première = fait.stdout.strip().splitlines()[0]
    morceaux = [m.strip() for m in première.split(',')]
    try:
        return {'utilisation_pct': float(morceaux[0]), 'memoire_utilisee_mo': float(morceaux[1]),
                'memoire_totale_mo': float(morceaux[2])}
    except (IndexError, ValueError):
        return None


def executions_simultanees():
    """Plafond d'exécutions simultanées : réglage explicite, sinon mémoire et charge."""
    force = os.environ.get('MC_MAX_JOBS')
    if force:
        try:
            return max(1, int(force))
        except ValueError:
            pass
    libre = memoire_libre_mo()
    charge = cpu_charge()
    if libre is None:
        return 1
    if libre < 2500:
        return 1
    plafond = 2 if libre < 6000 else 3
    if charge is not None and charge > 85:
        plafond = 1
    gpu = gpu_info()
    if gpu and gpu.get('utilisation_pct', 0) > 80:
        plafond = max(1, plafond - 1)
    return max(1, plafond)


def valider_plan(plan, roles=None):
    """Contrôle la forme, les rôles et le graphe. Rend des tâches normalisées."""
    if not isinstance(plan, dict):
        raise PlanInvalide('Plan illisible : objet JSON attendu')
    objectif = str(plan.get('objective', '')).strip()
    taches = plan.get('tasks')
    if not isinstance(taches, list) or not taches:
        raise PlanInvalide('Aucune tâche proposée')
    if len(taches) > MAX_TACHES:
        raise PlanInvalide('Trop de tâches (%d, maximum %d)' % (len(taches), MAX_TACHES))
    propres = []
    for rang, tache in enumerate(taches):
        if not isinstance(tache, dict):
            raise PlanInvalide('Tâche %d illisible' % rang)
        titre = str(tache.get('title', '')).strip()[:160]
        travail = str(tache.get('task', '')).strip()[:5000]
        role = str(tache.get('role', '')).strip()
        if not titre or not travail:
            raise PlanInvalide('Tâche %d sans titre ou sans travail' % rang)
        if role not in (roles or ROLES):
            raise PlanInvalide('Tâche %d : rôle inconnu « %s »' % (rang, role))
        deps = tache.get('depends_on') or []
        if not isinstance(deps, list):
            raise PlanInvalide('Tâche %d : dépendances illisibles' % rang)
        deps = sorted({int(x) for x in deps})
        for d in deps:
            if d == rang or d < 0 or d >= len(taches):
                raise PlanInvalide('Tâche %d : dépendance invalide %s' % (rang, d))
        propres.append({'index': rang, 'title': titre, 'task': travail, 'role': role, 'depends_on': deps})
    # Cycles : tri topologique.
    restants = {t['index']: set(t['depends_on']) for t in propres}
    vus = set()
    while restants:
        prets = [i for i, deps in restants.items() if deps <= vus]
        if not prets:
            raise PlanInvalide('Dépendances circulaires dans le plan')
        for i in prets:
            vus.add(i)
            del restants[i]
    return {'objective': objectif, 'tasks': propres}


def competences(agent):
    return {c.strip().lower() for c in str(agent.get('skills') or '').split(',') if c.strip()}


def choisir_agent(agents, role, charge, competences_demandees=None):
    """Agent du rôle demandé : compétences d'abord, puis charge la plus faible."""
    demandees = {c.strip().lower() for c in (competences_demandees or []) if str(c).strip()}
    candidats = [a for a in agents if a['role'] == role and a.get('status') in ('idle', 'working', 'paused')]
    if not candidats:
        return None
    def score(a):
        communes = len(competences(a) & demandees)
        return (-communes, charge.get(a['id'], 0), a['id'])
    return min(candidats, key=score)


def taches_pretes(taches, etats):
    """Tâches dont toutes les dépendances sont approuvées ou terminées."""
    return [t for t in taches
            if t['status'] in ('queued', 'blocked')
            and all(etats.get(d) in ('approved', 'completed') for d in (t.get('depends') or []))]
