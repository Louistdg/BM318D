# Livraison V2.8.2 — fin du decoupage

Date : 19/10/2026. Base : v2.8.1. Aucun changement de comportement.

## `mc_agents.py`

Sortis de `MissionControl.py` : roles, permissions par equipe, branches, clones,
recrutement, archivage, charge par agent, plans et orchestrateur.

```
mc_agents.py   307 lignes
```

`MissionControl.py` : 868 -> 639 lignes. `_dispatch` reste a 11 lignes, la table
des routes a 44 entrees.

## `operator()` : intention explicite

La signature trompeuse signalee par l'audit est traitee sans changer le
comportement : les parametres `expected`/`expected_admin` sont acceptes pour la
compatibilite mais supprimes par `del`, avec une docstring qui dit pourquoi. Un
appelant ne peut toujours pas imposer son propre secret.

## Verification

```
test_all.cmd          SUCCES, 71 ok sur la derniere suite
test_permissions_v23  21/21
test_jobs.py          53/53
test_http.py          40/40
test_securite.py      67 ok
test_corbeille.py     5/5
```
