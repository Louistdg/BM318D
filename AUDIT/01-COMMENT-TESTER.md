# Comment tester — commandes exactes

Toutes les commandes ci-dessous ont été exécutées sur Windows 11 avec
`C:\Python314\python.exe` (Python 3.14.7) et `python` (3.15.0) pour les tests.

## 1. Compilation

```cmd
cd source
C:\Python314\python.exe -m py_compile *.py
```

Résultat attendu : aucune sortie, code de sortie 0.

## 2. Tests complets

```cmd
cd source
test_all.cmd
```

Douze étapes, chacune affichant `ok` ou `ECHEC` :

```
[01/12 - Contrat documents]    16 ok
[02/12 - Application]          44 ok
[03/12 - Sécurité]             ...
[04/12 - ...
...
[12/12 - Interface Chrome]     71 ok
=== SUCCES : toutes les verifications sont passees ===
```

Durée observée : 8 à 12 minutes. Les tests utilisent une base temporaire et
n'ouvrent jamais la base de production.

Pour une seule suite :

```cmd
python test_documents.py
python test_securite.py
python test_sandbox_v23.py
python test_connectors_securite.py
```

## 3. Démarrage isolé (sans toucher à une installation existante)

```cmd
cd source
set MC_DB=%TEMP%\audit-31880.sqlite3
set MC_PORT=31880
C:\Python314\python.exe MissionControl.py
```

Attendu :

```
BM318d Mission Control http://127.0.0.1:31880/ (jeton de session actif)
```

Puis, dans un autre terminal :

```cmd
curl -s -o NUL -w "%{http_code}" http://127.0.0.1:31880/
curl -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:31880/api/mc/connectors/save
```

Attendu : `200` pour la page, `403` pour l'appel sans jeton administrateur.

## 4. Base de données

```cmd
python -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print(c.execute('pragma integrity_check').fetchone()[0]);print(len(c.execute(\"select name from sqlite_master where type='table'\").fetchall()),'tables')" %TEMP%\audit-31880.sqlite3
```

Attendu : `ok` puis `28 tables`.

## 5. Import et restauration (le scénario de la version 2.5.1)

Les tests `test_documents.py` couvrent : import, sauvegarde `.sqlite3` +
`.imports.zip`, suppression du fichier, restauration, et **refus HTTP 409**
quand le fichier local a été modifié entre-temps.

```cmd
python test_documents.py
```

## 6. Installateur

```cmd
04-INSTALLATEUR\DIOPTRE-Setup-2.5.3.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
dir %LOCALAPPDATA%\DIOPTRE
```

Attendu : 31 fichiers dans `%LOCALAPPDATA%\DIOPTRE`, raccourci Bureau, menu
Démarrer, `unins000.exe`. Désinstallation : `unins000.exe /VERYSILENT`.

## 7. Variables d'environnement utiles

Aucune n'est obligatoire.

```
MC_DB              chemin de la base SQLite
MC_PORT            port d'écoute (31880)
MC_TOKEN           jeton de session imposé
MC_ADMIN_TOKEN     jeton administrateur imposé
MC_RATE_LIMIT      requêtes par minute et par IP
MC_MAX_JOBS        jobs simultanés
MC_WORKSPACES      dossier des espaces de travail
MC_OLLAMA_MODEL    modèle par défaut
MC_SANDBOX         active ou désactive le bac à sable
```

## 8. Ce qui ne peut pas être testé ailleurs

- le bac à sable Windows (jeton restreint, intégrité basse, objet job) ;
- les applications Tkinter (`BM318d-Controleur.pyw`, `BM318d-Stop.py`) ;
- l'intégration Ollama sur GPU (la carte testée n'est pas compilée dans cette
  version, tout tourne en CPU).
