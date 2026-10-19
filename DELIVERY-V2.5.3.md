# Livraison V2.5.3 — finitions documents

Date : 19/10/2026. Base : tag v2.5.2.

## Corrections

1. **Revision explicite.** Supprimer ou modifier une fiche sans fournir `revision`
   repondait « Identifiant invalide ». Le message dit maintenant
   « Revision requise pour supprimer la fiche : recharge la fiche avant de
   reessayer ».

2. **Corbeille des fichiers importes.** Supprimer une fiche ne laissait le
   fichier ni suivi ni efface : il restait dans `fichiers-importes/` et sortait
   des sauvegardes. Il est maintenant deplace dans
   `workspace/corbeille/<horodatage>-p<projet>-<id>-<nom>`, recuperable a la
   main, et la reponse indique son chemin (`corbeille`).

3. **Deux sauvegardes dans la meme seconde.** Le nom par defaut etait a la
   seconde ; la seconde sauvegarde echouait. Horodatage a la microseconde.

## Verification

- 16 tests documents (dont 2 nouveaux) : OK.
- Preuve negative : sans les correctifs, 2 tests echouent.
- `test_all.cmd` : a relancer avant diffusion.

## Limites

- La corbeille n'est jamais purgee automatiquement : c'est volontaire
  (recuperation), mais l'espace disque n'est pas libere.
- Une fiche supprimee reste en base (`deleted_at`) : pas de purge d'historique.
