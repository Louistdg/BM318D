"""BM318d — arrêt propre : demande au serveur local de s'arrêter, avec le jeton.

Le jeton est lu dans la page servie (il change à chaque démarrage). Aucun mot de
passe n'est stocké sur le disque.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

PORT = int(os.environ.get('MC_PORT') or 31880)
URL = 'http://127.0.0.1:%d/' % PORT


def main():
    try:
        with urllib.request.urlopen(URL, timeout=5) as r:
            html = r.read().decode('utf-8', 'replace')
    except Exception as e:
        print('Serveur injoignable : ' + str(e))
        return 2
    trouve = re.search(r'name="mc-token" content="([^"]+)"', html)
    if not trouve:
        print('Jeton introuvable dans la page')
        return 2
    requete = urllib.request.Request(URL + 'api/mc/shutdown',
                                     data=json.dumps({'project': 1}).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'X-MC-Token': trouve.group(1)},
                                     method='POST')
    try:
        with urllib.request.urlopen(requete, timeout=5) as r:
            print('Arrêt demandé : ' + r.read().decode('utf-8', 'replace'))
        return 0
    except urllib.error.HTTPError as e:
        print('Refus du serveur : %s %s' % (e.code, e.read().decode('utf-8', 'replace')[:200]))
        return 1


if __name__ == '__main__':
    sys.exit(main())
