# Livraison V2.6.2 — diagnostic du coffre

Date : 19/10/2026. Base : v2.6.1. Un seul changement.

## Coffre : distinguer « cle absente » et « coffre en panne »

La reprise des anciennes cles (2.6.1) passe par une lecture interne `_lire()`.
Celle-ci rendait `None` pour toute erreur, si bien qu'un coffre defaillant
ressemblait a une cle absente.

Desormais : code 1168 (`ERROR_NOT_FOUND`) -> `None`, toute autre erreur ->
`ValueError('Coffre Windows indisponible')`. Meme comportement fonctionnel,
diagnostic correct.

## Verification

- `test_renommage_260.py` : 4 tests, dont la reprise reelle d'une cle.
- `test_all.cmd` : SUCCES.
