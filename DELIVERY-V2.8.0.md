# Livraison V2.8.0 — fin du demontage du serveur

Date : 19/10/2026. Base : v2.7.0. Aucun changement de comportement : uniquement
de la structure.

## Ce qui a ete supprime

- `DIOPTRE-WebServer.py` : second serveur HTTP (port 31879) sans authentification,
  charge par `importlib` et herite par sous-classement. Supprime.
- Le chargement dynamique dans `MissionControl.py` : plus de `spec_from_file_location`.
- Les `CREATE TABLE` executes a l'import de ce module : la creation des tables est
  desormais uniquement dans `init()`.
- `_guard_function` et son rebinding dans `globals()`.
- La chaine de `if path==...` de 94 lignes dans `_dispatch`.

## Ce qui a ete cree

| Module | Lignes | Role |
|---|---|---|
| `mc_actions.py` | 34 | decorateur `@action`, remplace `_guard_function` |
| `mc_routes.py` | 72 | table declarative : 43 routes, chemin -> fonction |
| `mc_jobs.py` | 324 | cycle de vie des jobs, preuves, revues, validation |
| `mc_missions.py` | 228 | missions, affectations, notes, decisions, messages, passations |
| `mc_backups.py` | 99 | sauvegarde, restauration, rotation |
| `mc_legacy.py` | 239 | les neuf routes historiques, servies par le serveur unique |

`MissionControl.py` passe de 1 340 a 868 lignes. `_dispatch` fait 10 lignes.

## Ce qui change pour l'utilisateur

Rien, volontairement. Les routes repondent pareil, les codes et les messages
d'erreur aussi. Deux details changent en mieux :

- les routes historiques (`/api/state`, `/api/task`, `/api/event`, `/api/ollama`)
  passent par le meme controle d'hote, d'origine, de jeton et de debit que le
  reste : il n'existe plus de port sans authentification ;
- `LANCER-DIOPTRE-RAILWAY.cmd` lance le serveur authentifie.

## Verification

```
test_all.cmd          SUCCES, 12 etapes, 70 ok sur la derniere suite
test_jobs.py          53/53
test_http.py          40/40
test_permissions_v23  21/21
test_securite.py      67 ok
test_documents.py     18/18 · test_renommage_260 4/4 · test_demo 3/3
```

## Limite

Les fonctions d'agents et de plans (`agent_clone`, `plan_proposer`,
`orchestrateur_lancer`...) sont encore dans `MissionControl.py`. Le prochain
decoupage les concernera ; rien n'est casse en attendant, elles restent
accessibles et protegees par le meme decorateur.
