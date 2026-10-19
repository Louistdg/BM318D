"""Sauvegardes, restauration et rotation.

Extrait de MissionControl.py : les fonctions ne dependent plus de l'etat global
du serveur, elles recoivent la racine, le chemin de la base et, pour la
restauration, les fonctions d'audit et de migration.
"""
import datetime
import sqlite3
import time

import mc_documents


def _texte(d, k, maxlen=500):
    v = str(d.get(k, '')).strip()
    if not v or len(v) > maxlen:
        raise ValueError('Champ invalide: ' + k)
    return v


def sauvegarder(racine, base, destination=None, *, inclure_imports=True):
    """Copie en ligne via l'API SQLite : coherente meme si le serveur ecrit."""
    if not base.is_file():
        return None
    if destination is None:
        destination = racine / 'backups' / ('dioptre-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    destination = destination if hasattr(destination, 'parent') else racine / 'backups' / str(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(base, timeout=20)
    try:
        cible = sqlite3.connect(destination)
        try:
            source.backup(cible)
        finally:
            cible.close()
    finally:
        source.close()
    if inclure_imports:
        mc_documents.backup_imports(destination, destination.with_suffix('.imports.zip'))
    return destination


def disponibles(racine):
    dossier = racine / 'backups'
    if not dossier.exists():
        return []
    return [{'nom': f.name, 'octets': f.stat().st_size,
             'quand': datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec='seconds'),
             'fichiers_importes': f.with_suffix('.imports.zip').is_file()}
            for f in sorted(dossier.glob('*.sqlite3'), key=lambda x: x.stat().st_mtime, reverse=True)[:30]]


def restaurer(c, p, d, *, racine, base, audit, init):
    nom = _texte(d, 'file', 200)
    dossier = (racine / 'backups').resolve()
    source = (dossier / nom).resolve()
    if source.parent != dossier or not source.exists():
        raise ValueError('Sauvegarde introuvable dans backups/ : ' + nom)
    securite = sauvegarder(racine, base,
                           racine / 'backups' / ('dioptre-avant-restauration-'
                                                 + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3'),
                           inclure_imports=False)
    archive = source.with_suffix('.imports.zip')
    # Valider le contenu de l'archive et les conflits locaux avant de remplacer la base.
    fichiers = mc_documents.restore_imports(source, archive)
    origine = sqlite3.connect(source)
    cible = sqlite3.connect(base)
    try:
        origine.backup(cible)
    finally:
        cible.close()
        origine.close()
    init()  # Reappliquer les migrations additives d'une base anterieure a V2.2.
    audit(c, p, 'database_restored', {'file': nom, 'sauvegarde_prealable': securite.name,
                                      'fichiers_restaures': fichiers})
    return {'ok': True, 'sauvegarde_prealable': securite.name, 'fichiers_restaures': fichiers,
            'avertissement': None if archive.is_file() else 'Sauvegarde ancienne sans archive de fichiers importés'}


def rotation(racine, limite=10):
    dossier = racine / 'backups'
    candidats = list(dossier.glob('dioptre-auto-*.sqlite3')) + list(dossier.glob('bm318d-auto-*.sqlite3'))
    vieux = sorted(candidats, key=lambda x: x.stat().st_mtime, reverse=True)[limite:]
    for fichier in vieux:
        fichier.unlink(missing_ok=True)
        fichier.with_suffix('.imports.zip').unlink(missing_ok=True)
    return len(vieux)


def boucle(racine, base, minutes):
    while True:
        time.sleep(max(60, int(minutes) * 60))
        try:
            dossier = racine / 'backups'
            sauvegarder(racine, base,
                        dossier / ('dioptre-auto-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3'))
            rotation(racine, 10)
        except Exception:
            pass
