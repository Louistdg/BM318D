# Livraison V2.5.2 — correctif A1

Date : 19/10/2026. Base de depart : tag v2.5.1 (dbea4f3).

## Correctif

Une restauration refusee parce qu'un fichier importe a ete modifie localement
repond maintenant **HTTP 409** avec un corps JSON explicite
(`{"error": "Fichier local different : <chemin>"}`), au lieu de fermer la
connexion sans reponse. Le fichier local n'est jamais ecrase.

Cause : `mc_documents.restore_imports` leve `FileExistsError`, que
`MissionControl.do_POST` n attrapait pas.

## Verification

- Test de non-regression ajoute dans `test_documents.py`
  (`test_restore_conflict_returns_http_409_json`) : 409, JSON, message, fichier intact.
- Preuve negative : sans le correctif, ce test echoue.
- Preuve A1 de bout en bout sous Python 3.14 : import, sauvegarde `.sqlite3` +
  `.imports.zip`, restauration, SHA-256 identique, conflit refuse — 22/22.
- `test_all.cmd` : 12 etapes, SUCCES, derniere suite 71 ok.

## Limites connues

- La restauration depuis une sauvegarde dont le manifeste designe un autre
  workspace est refusee (chemin absolu enregistre).
- Les erreurs de disque hors conflit de fichier restent en 400.
