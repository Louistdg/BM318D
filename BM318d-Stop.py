"""BM318d — arrêt propre : le serveur ne s'arrête qu'avec le jeton administrateur local.

Le jeton de session est lu dans la page. Le jeton administrateur est lu dans
logs/admin-token.txt, à côté de ce script. Aucun des deux n'est affiché.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PORT = int(os.environ.get('MC_PORT') or 31880)
URL = 'http://127.0.0.1:%d/' % PORT
RACINE = Path(__file__).resolve().parent


def jeton_admin():
    chemin = RACINE / 'logs' / 'admin-token.txt'
    if not chemin.is_file():
        return None
    valeur = chemin.read_text(encoding='utf-8').strip()
    return valeur or None


def main():
    try:
        with urllib.request.urlopen(URL, timeout=5) as r:
            html = r.read().decode('utf-8', 'replace')
    except Exception:
        print("Serveur injoignable. Rien n'a été arrêté.")
        return 2
    trouve = re.search(r'name="mc-token" content="([^"]+)"', html)
    if not trouve:
        print('Jeton de session introuvable. Le service tourne encore.')
        return 2
    admin = jeton_admin()
    if not admin:
        print('Arrêt non confirmé : jeton administrateur absent. Le service tourne encore.')
        return 1
    session = trouve.group(1)
    projet = 1
    try:
        etat_req = urllib.request.Request(URL + 'api/state', headers={'X-MC-Token': session})
        with urllib.request.urlopen(etat_req, timeout=5) as r:
            etat = json.loads(r.read().decode('utf-8', 'replace'))
        projets = etat.get('projects') or []
        if projets and projets[0]:
            projet = int(projets[0][0])
    except Exception:
        projet = 1
    requete = urllib.request.Request(URL + 'api/mc/shutdown',
                                     data=json.dumps({'project': projet}).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'X-MC-Token': session,
                                              'X-MC-Admin': admin},
                                     method='POST')
    try:
        with urllib.request.urlopen(requete, timeout=5) as r:
            corps = json.loads(r.read().decode('utf-8', 'replace'))
        if not isinstance(corps, dict) or corps.get('ok') is not True:
            print('Arrêt non confirmé. Le service tourne encore.')
            return 1
        print('Arrêt confirmé par le serveur.')
        return 0
    except urllib.error.HTTPError as e:
        print('Arrêt non confirmé (code %s). Le service tourne encore.' % e.code)
        return 1
    except Exception:
        print('Arrêt non confirmé. Le service tourne encore.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
