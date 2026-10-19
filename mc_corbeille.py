"""Purge des fichiers supprimes (corbeille des espaces de travail).

Un fichier supprime quitte `fichiers-importes/` pour `corbeille/` : il reste
recuperable, mais rien ne le supprimait jamais. Cette purge applique une duree de
retention et, si demande, un plafond de taille.

Aucune suppression n'est faite sans que la duree soit ecoulee. Le mode simulation
compte sans rien effacer.
"""
import datetime
from pathlib import Path

RETENTION_JOURS = 30
TAILLE_MAX_MO_DEFAUT = 0  # 0 = pas de plafond


def _dossiers(racines):
    """Rend chaque dossier nomme `corbeille` trouve sous les racines donnees."""
    vus = set()
    for racine in racines:
        racine = Path(racine)
        if not racine.exists():
            continue
        for dossier in [racine / 'corbeille'] + [p for p in racine.glob('*/corbeille') if p.is_dir()]:
            if dossier.is_dir():
                cle = str(dossier.resolve()).lower()
                if cle not in vus:
                    vus.add(cle)
                    yield dossier


def etat(racines):
    """Resume de la corbeille : nombre de fichiers, octets, plus ancien."""
    total = 0
    octets = 0
    plus_ancien = None
    for dossier in _dossiers(racines):
        for fichier in dossier.rglob('*'):
            if not fichier.is_file():
                continue
            total += 1
            info = fichier.stat()
            octets += info.st_size
            quand = datetime.datetime.fromtimestamp(info.st_mtime)
            if plus_ancien is None or quand < plus_ancien:
                plus_ancien = quand
    return {'fichiers': total, 'octets': octets,
            'plus_ancien': plus_ancien.isoformat(timespec='seconds') if plus_ancien else None,
            'jours': RETENTION_JOURS}


def purger(racines, jours=RETENTION_JOURS, taille_max_mo=TAILLE_MAX_MO_DEFAUT, *, simulation=False):
    """Supprime les fichiers de corbeille plus vieux que `jours`.

    Si `taille_max_mo` est positif, supprime aussi les plus anciens restants
    jusqu'a repasser sous le plafond. Rend un compte rendu chiffre.
    """
    limite = datetime.datetime.now() - datetime.timedelta(days=max(1, int(jours)))
    supprimes = 0
    octets = 0
    epargnes = 0
    candidats = []
    for dossier in _dossiers(racines):
        for fichier in dossier.rglob('*'):
            if not fichier.is_file():
                continue
            try:
                info = fichier.stat()
            except OSError:
                continue
            quand = datetime.datetime.fromtimestamp(info.st_mtime)
            if quand < limite:
                candidats.append((quand, fichier, info.st_size))
            else:
                epargnes += 1
    for _, fichier, taille in sorted(candidats):
        if not simulation:
            try:
                fichier.unlink()
            except OSError:
                continue
        supprimes += 1
        octets += taille
    # plafond de taille sur ce qui reste
    if taille_max_mo and taille_max_mo > 0:
        restants = []
        for dossier in _dossiers(racines):
            for fichier in dossier.rglob('*'):
                if fichier.is_file():
                    try:
                        info = fichier.stat()
                    except OSError:
                        continue
                    restants.append((info.st_mtime, fichier, info.st_size))
        total = sum(taille for _, _, taille in restants)
        plafond = taille_max_mo * 1024 * 1024
        for _, fichier, taille in sorted(restants):
            if total <= plafond:
                break
            if not simulation:
                try:
                    fichier.unlink()
                except OSError:
                    continue
            total -= taille
            supprimes += 1
            octets += taille
    return {'supprimes': supprimes, 'octets': octets, 'conserves': epargnes,
            'retention_jours': int(jours), 'simulation': bool(simulation)}
