# DIOPTRE / BM318D 2.5.3 — dossier d'audit

Merci de faire l'audit de cette application. Ce document dit ce qu'elle est,
comment la lancer, ce qui est déjà vérifié, ce qui est fragile, et ce que
j'attends d'un audit sérieux.

## 1. En deux phrases

DIOPTRE est le nom public d'un logiciel Windows (nom de code BM318D) qui
centralise projets, tâches, agents IA, documents et preuves, avec un assistant
local. C'est une application **Python 3.14, bibliothèque standard uniquement**,
qui sert une interface web sur `127.0.0.1:31880` et parle à **Ollama** en local.

## 2. Contenu du dossier

```
00-LIRE-EN-PREMIER.md      ce document
01-COMMENT-TESTER.md       commandes exactes, résultats attendus
02-PREUVES/                sorties brutes des tests, de l'installation, du démarrage
03-CAPTURES/               captures de l'application et de la vitrine
04-INSTALLATEUR/           DIOPTRE-Setup-2.5.3.exe (Inno Setup)
source/                    code complet au tag v2.5.3, sans historique ni données
MANIFESTE-SHA256.txt       empreinte de chaque fichier
```

`souce/` contient notamment : `MissionControl.py` (serveur et routes),
`mc_security.py` (jetons, en-têtes, permissions), `mc_sandbox*.py` (exécution
confinée), `mc_connectors.py` (fournisseurs IA et quotas), `mc_documents.py`
(import, sauvegarde ZIP, restauration), `mc_agent.py`, `mc_plan.py`, l'interface
(`mission.js`, `workspace.js`, `connectors.js`, CSS) et la suite de tests.

## 3. Comment lancer

Windows 10/11, Python 3.14, aucune dépendance à installer pour le socle.

```cmd
cd source
set MC_DB=%TEMP%\audit.sqlite3
set MC_PORT=31880
C:\Python314\python.exe MissionControl.py
```

Puis `http://127.0.0.1:31880/`. Le jeton de session est dans la page HTML
(balise meta `mc-token`) ; le jeton administrateur est écrit au démarrage dans
`<dossier de la base>\logs\admin-token.txt` ou affiché en console.

Sous Linux, le serveur démarre mais le bac à sable Windows et les applications
Tkinter ne fonctionnent pas. C'est documenté comme limite, pas comme bug.

## 4. Ce qui est déjà vérifié (preuves dans 02-PREUVES)

- compilation Python : code 0
- installation par l'installateur : 27 fichiers, code 0
- `test_all.cmd` : 12 étapes, `SUCCES`, dernière suite 71/71
- démarrage isolé : HTTP 200, version 2.5.3, 403 sans jeton admin
- base SQLite : `integrity_check = ok`, `foreign_key_check` vide, 28 tables
- import/restauration : fichier importé, sauvegarde ZIP avec empreintes,
  restauration identique au SHA-256 près, refus (HTTP 409) si le fichier local
  a été modifié

## 5. Ce que je veux faire auditer, par ordre de priorité

1. **Sécurité du serveur HTTP** : vérification d'hôte et d'origine, gestion des
   jetons (session + admin), permissions par équipe, limites de taille et de
   débit, chemins de traverse (`../`), injection dans les routes.
2. **Bac à sable d'exécution** (`mc_sandbox*.py`) : échappement possible,
   héritage de handles, accès réseau de l'enfant, fichiers accessibles hors du
   dossier de travail.
3. **Connecteurs IA** (`mc_connectors.py`) : SSRF, redirection vers une adresse
   interne, fuite de clés, quotas, bascule entre fournisseurs, MCP verrouillé.
4. **Module documents** (`mc_documents.py`) : traversée de chemin, ZIP piégé
   (zip bomb, entrées hors dossier), écrasement silencieux, cohérence
   manifeste/base.
5. **SQLite** : concurrence (threads + écritures), migrations additives,
   sauvegarde en ligne, restauration.
6. **Interface** : XSS dans les champs libres, injection dans les attributs,
   comportement quand Ollama est absent.

## 6. Limites connues, à ne pas présenter comme des découvertes

- **Exécutable non signé** : Windows affiche un avertissement SmartScreen.
- **Bac à sable Windows uniquement** : sous Linux, aucune isolation n'est
  appliquée (le module le dit et refuse).
- **Lecture hors workspace non confinée** : le bac à sable restreint les
  privilèges, pas la lecture de fichiers.
- **Réseau de l'enfant non filtré** : un job sandboxé peut ouvrir une connexion.
- **SQLite mono-fichier, mono-utilisateur** : pas de multi-écriture distribuée.
- **Ollama requis pour le chat** : sans lui, le reste fonctionne, le chat non.
- **Deux interpréteurs** : service en 3.14, tests en 3.15.
- **Pas de test sur une installation Windows vierge** ni sur un hébergement Linux.

## 7. Hors périmètre

La vitrine publique (`https://dioptre.socle-construction.be`) est un site
statique séparé, présent ici seulement en captures. Elle ne fait pas partie de
l'audit du logiciel.

## 8. Ce que j'attends en retour

- les vulnérabilités, classées par gravité, avec le fichier et la ligne ;
- pour chacune : comment la reproduire, et la correction proposée ;
- ce qui a été testé sans rien trouver (pour ne pas refaire le travail) ;
- une note sur trois axes : sécurité, robustesse, qualité du code ;
- la liste des questions auxquelles le code ne permet pas de répondre.
