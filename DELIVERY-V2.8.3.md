# Livraison V2.8.3 — decoupage termine

Date : 19/10/2026. Base : v2.8.2. Aucun changement de comportement.

## `mc_store.py`

Sortis de `MissionControl.py` : reglages de projet, recherche, notifications,
historique.

```
mc_store.py   71 lignes
```

## Etat du decoupage

| Module | Lignes |
|---|---|
| `mc_jobs.py` | 324 |
| `mc_agents.py` | 292 |
| `mc_missions.py` | 228 |
| `mc_legacy.py` | 239 |
| `mc_backups.py` | 99 |
| `mc_routes.py` | 72 |
| `mc_store.py` | 71 |
| `mc_corbeille.py` | 99 |
| `mc_actions.py` | 34 |
| **`MissionControl.py`** | **593** |

`MissionControl.py` : 1 340 -> 593 lignes. `_dispatch` : 11 lignes.
La cible « environ 500 » est presque atteinte ; ce qui reste est le serveur HTTP
lui-meme (handler, controles, limites) et le point d'entree.

## Verification

```
test_all.cmd          SUCCES, 71 ok sur la derniere suite
test_permissions_v23  21/21
```
