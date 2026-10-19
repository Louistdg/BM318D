# Livraison V2.6.0 — renommage complet en DIOPTRE

Date : 19/10/2026. Base : v2.5.4.

## Renommage

Tout ce qui portait encore le nom de code est renommé :

```
DIOPTRE-Controleur.pyw      DIOPTRE-Stop.py          DIOPTRE-WebServer.py
DIOPTRE-Railway -> DIOPTRE.html                     DIOPTRE.pyw, DIOPTRE-Fenetre.pyw,
DIOPTRE-Studio.pyw, DIOPTRE-Unifie.pyw, DIOPTRE-Extensions.pyw
LANCER-DIOPTRE.cmd, LANCER-DIOPTRE-RAILWAY.cmd, LANCER-DIOPTRE-STUDIO.cmd,
LANCER-DIOPTRE-UNIFIE.cmd, OUVRIR-DIOPTRE.cmd, ARRETER-DIOPTRE.cmd
installer/DIOPTRE-Setup.ps1, installer/DIOPTRE-Update.ps1
DIOPTRE-LISEZMOI.txt
```

La base s'appelle désormais `dioptre.sqlite3`. Au premier démarrage, si
`bm318d.sqlite3` existe encore, elle est reprise automatiquement : aucune
donnée n'est perdue, aucune action manuelle.

Les sauvegardes automatiques s'appellent `dioptre-auto-*.sqlite3`.

## Vérification

- compilation des 53 fichiers Python : 0 erreur ;
- `test_all.cmd` : 12 étapes, SUCCES ;
- migration testée : une base `bm318d.sqlite3` est bien reprise en `dioptre.sqlite3`.

## Limite

Les dossiers de développement (`D:\BM318d-Control-Center`, `D:\BM318d-Supervision`,
`D:\BM318d-worktrees`) gardent leur nom : les renommer casserait le service en
cours, les scripts de supervision et les chemins de sauvegarde. C'est un
renommage d'exploitation, à faire à froid, hors livraison.
