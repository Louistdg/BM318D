# Livraison V2.7.0 — mode demonstration

Date : 19/10/2026. Base : v2.6.2.

## Le probleme

Une installation fraiche est vide : aucune donnee, aucune explication. La
premiere impression d'un outil de pilotage est un canvas blanc.

## La reponse

`mc_demo.py` cree un projet complet et **coherent**, avec de vraies traces :

- 1 projet, 3 agents (chef de projet, developpeur, relectrice) ;
- 1 mission « Livrer l'export CSV du module export » ;
- 1 affectation, 1 job, 1 proposition, 1 diff, 1 fichier ecrit ;
- une verification **reellement executee** : `python -m py_compile export_csv.py`,
  dont le code de sortie et la duree sont enregistres comme preuve ;
- 1 revue `ok`, 1 note de decision, 1 entree d'audit.

Aucune valeur inventee : si la compilation echoue, tout est annule et la
demonstration est refusee.

## Utilisation

```cmd
python mc_demo.py                  cree la demonstration
python mc_demo.py --force          la recree
python MissionControl.py --demo    idem depuis le lanceur principal
LANCER-DIOPTRE-DEMO.cmd            depuis une installation (nouveau)
```

Idempotent : deux appels sans `--force` ne creent pas de doublon.

## Verification

- `test_demo.py` : 3 tests (creation complete, preuve reelle, pas de doublon,
  recreation sans empilement) ;
- `test_all.cmd` : SUCCES.
