# Livraison V2.8.1 — purge de la corbeille

Date : 19/10/2026. Base : v2.8.0.

## Le probleme

Un fichier supprime quitte `fichiers-importes/` pour `corbeille/` : il reste
recuperable, mais rien ne le supprimait jamais. Le dossier grandissait sans
limite, sans que personne ne le voie.

## La reponse

`mc_corbeille.py` :

- retention par defaut **30 jours**, supprime les fichiers plus anciens ;
- plafond de taille optionnel (`taille_max_mo`), qui retire les plus anciens
  jusqu'a repasser sous le plafond ;
- mode `simulation` : compte sans rien effacer ;
- compte rendu chiffre (supprimes, octets, conserves).

Branchements :

- **automatique** a chaque cycle de sauvegarde (`boucle_sauvegardes`), donc une
  fois par heure quand la sauvegarde automatique est active ;
- **manuel** par `POST /api/mc/corbeille/purge`, reserve au jeton administrateur,
  avec `jours`, `taille_max_mo` et `simulation`.

## Verification

`test_corbeille.py` : 5 tests (etat, simulation sans effacement, purge selective,
plafond de taille, presence de la route). Suite complete : SUCCES.

## Limite

La purge est best-effort : un fichier verrouille est ignore, pas force.
