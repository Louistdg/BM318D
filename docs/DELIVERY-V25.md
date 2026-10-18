# BM318d V2.5 — refonte de l’espace projet (branche isolée)

Date : 18 octobre 2026. **Non déployé.** Travail réalisé dans `D:\BM318d-worktrees\codex-v24-delivery`, branche `codex/v25-railway-workspace`, base initiale `7f011073`.

## Fait vérifié

- Le dépôt a été inspecté avec `git status --short --branch`, `git worktree list` et la recherche de `AGENTS.md` ; aucun `AGENTS.md` dans ce worktree. Le fichier préexistant non suivi `test_documents.py` a été conservé sans changement.
- L'ancien canevas devient l'accueil, avec ses positions, déplacements et dépendances conservés ; Mission Control reste accessible par la navigation.
- Navigation latérale : intitulés lisibles, repli/extension, largeur réglable et sauvegardée localement, touches fléchées et format réduit.
- Vue d'ensemble : calculs depuis les tâches du projet, agents, missions, jobs et attributions effectivement enregistrés. Les agents absents ne sont pas simulés.
- Chat : espace étendu, modèle près de l'envoi, stockage local existant des conversations conservé, pièces jointes associées aux messages, sélection du modèle par conversation. Les autorisations de l'agent et le backend Ollama sont inchangés.
- Dossiers et fiches : nouveau stockage SQLite `mc_documents`, contenu de type note/lien/information, dossiers parents, positions, édition, suppression logique avec confirmation, vérification de révision contre pertes d'écriture, contrôle du projet pour chaque opération, refus de déplacer un dossier dans ses descendants et refus de supprimer un dossier non vide.
- La migration crée uniquement une nouvelle table avec son index sur une copie et sauvegarde avant une première migration en environnement cible. Le programme n'a pas migré la base réelle.
- Une fonction d'édition des propriétés de tâche a été ajoutée avec contrôle serveur de l'appartenance au projet.

### Sorties conservées

```text
node test_ui.mjs
54 ok, 0 echec(s)

node test_chat_ui.mjs
17 ok, 0 echec(s)

node test_connectors_ui.mjs
16 ok, 0 echec(s)

node test_security_ui_v23.mjs
11 ok, 0 echec(s)

C:\Python314\python.exe test_http.py
37 ok, 0 echec(s)

C:\Python314\python.exe -m unittest -v test_documents
Ran 8 tests in 1.496s
OK
```

Les huit tests de documents échouaient **avant** les changements sur `sqlite3.OperationalError: no such table: mc_documents`. Après ajout de la table et du contrôleur, ils passent.

Contrôle de migration réel sur une copie isolée issue de `D:\BM318d-Control-Center\bm318d.sqlite3` :
```text
ORIGINAL_TABLES=26
CHANGED_EXISTING_TABLES={}
NEW_TABLES={"mc_documents": 0}
SQLITE_QUICK_CHECK=ok
FOREIGN_KEY_ERRORS=0
```
Comptes de référence principaux : 4 projets, 1 tâche, 55 événements, 0 agent Mission Control ; les 26 tables préexistantes ont conservé leurs nombres de lignes et leurs empreintes de contenu.

Observation directe dans un navigateur isolé : accueil canevas avec la tâche préexistante ; vue d'ensemble présentant un seul élément terminé et zéro agent fictif ; création effective d'un dossier et persistance visible ; navigation sur petit écran avec menu dépliable ; aucune erreur console observée dans ces parcours.

## Déclaré, non entièrement vérifié

- Aucun test humain exhaustif de toutes les combinaisons de gestes tactiles, glisser-déposer dans les dossiers et redimensionnement par souris.
- Pas de nouveau test sur un modèle Ollama réellement générant du texte au cours de cette version ; le chat utilise le même backend lecture seule que V2.4.
- La sauvegarde préalable de migration est prévue dans `init()` ; ne déclencher la migration sur la base principale qu'après contrôle humain du changement.
- Les données de conversations dépendent du stockage local du navigateur, comme auparavant ; elles ne se synchronisent pas entre navigateurs.
- Un avertissement Python `ResourceWarning` sur les connexions SQLite importées dans des tests existants persiste, sans échec des assertions.
- Les tests de l'écran bureau/téléphone ont couvert 1440px et un navigateur au format réduit 500px ; pas de preuve pour chaque taille possible.

## Hypothèses / limites

- L'inspiration Railway concerne l'organisation du canevas et le détail projet, non une reproduction pixel-perfect.
- La protection contre le déplacement entre projets est imposée par le serveur et vérifiée en test. Aucun accès supplémentaire aux fichiers n'a été octroyé aux agents.
- Aucune branche autre que `codex/v25-railway-workspace` n'a été modifiée ; aucune restauration, suppression de données ou déploiement n'a été effectué.

## À ne pas faire

Ne pas remplacer la base `D:\BM318d-Control-Center\bm318d.sqlite3` par une base de test, ne pas redéployer directement depuis l'ancienne release et ne pas activer MCP. Ne passer en production qu'après revue du diff, sauvegarde et contrôle des données dans la version candidate.
