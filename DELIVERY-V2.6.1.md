# Livraison V2.6.1 — reprise des anciennes donnees

Date : 19/10/2026. Base : v2.6.0. Corrige les deux remarques de la passe courte 2.6.0.

## 1. Cles du coffre Windows reprises automatiquement

Avant : la cible du coffre est passee de `BM318d/V2.2/connector/<uuid>` a
`DIOPTRE/V2.2/connector/<uuid>`. Les cles existantes devenaient invisibles
(echec propre, « Cle absente ») et l'ancienne entree restait a jamais.

Maintenant : a la lecture, si la nouvelle cible est absente, l'ancienne est lue,
recopiee sous le nouveau nom, puis supprimee. Aucune ressaisie, aucun secret
orphelin.

## 2. Rotation des sauvegardes etendue

La rotation ne regardait que `dioptre-auto-*.sqlite3`. Elle prend desormais en
compte `bm318d-auto-*.sqlite3` : les anciennes sauvegardes sont purgées selon la
meme limite que les nouvelles, au lieu de s'accumuler.

## Verification

- `test_renommage_260.py` : 4 tests (reprise de la base, non-ecrasement,
  rotation des deux prefixes, reprise d'une cle du coffre — ce dernier ecrit et
  relit une entree reelle dans le gestionnaire d'identifiants Windows).
- `test_all.cmd` : 13 etapes, SUCCES.
