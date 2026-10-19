# Livraison V2.8.4 — bac a sable reel, racines suivies, depot propre

Date : 19/10/2026. Base : v2.8.3.

## 1. Bac a sable WSL teste en conditions reelles

Sept essais executes sur le poste, Windows -> WSL -> bubblewrap + seccomp :

```
code python approuve          code 0, sortie capturee
reseau (1.1.1.1:80)           PermissionError : Operation not permitted
fork                          PermissionError : Operation not permitted
/etc/passwd de l hote         FileNotFoundError : absent du bac a sable
ecriture /tmp                 visible dedans, absente de l hote
runtime non approuve          Refus : Runtime non approuve
chemin hors workspace         Refus avant lancement
```

`test_sandbox_wsl_reel.py` : 7 tests, ignores si WSL ou bubblewrap manque.
Ajoute a `test_all.cmd`.

## 2. Changement de workspace : les fiches suivent

`mc_documents.reconcilier_racines(c, racine)` : une fiche n'est rattachee a la
nouvelle racine que si le fichier y existe et n'existe plus a l'ancienne. Rien
n'est deplace, rien n'est devine. Branche sur `reglage_definir` quand la cle est
`workspace_dir`, avec une entree d'audit `workspace_reconcilie`.

## 3. Depôt propre

Les sept scripts de developpement `patch_*.py` et `fix_*.py` passent dans
`outils-dev/`. La racine ne contient plus que code, tests, documentation et
installateur.

## Verification

```
test_all.cmd          SUCCES, 71 ok sur la derniere suite
test_documents.py     19/19 (dont le rattachement de racine)
test_sandbox_wsl_reel 7/7
```
