# Audit du site public (DIOPTRE)

Le dossier `site/` contient la vitrine publiée sur
`https://dioptre.socle-construction.be`. C'est un site **statique**, sans
serveur, sans base, sans API. Il ne fait que présenter le logiciel et proposer
son installateur.

## Ce qu'il contient

- `index.html` : page d'accueil, 368 Ko (quatre captures intégrées en base64)
- `installation.html` : guide d'installation
- `favicon.svg`, `robots.txt`, `sitemap.xml`
- `assets/02-mission-control.jpg` : image de partage (og:image)

## Ce qui est déjà vérifié

- aucune requête externe : CSS inline, images en data URI, aucune police distante ;
- aucun traceur, aucun cookie, aucun stockage hors `localStorage` pour le thème ;
- deux thèmes, bascule mémorisée, testés en 1440 px et 390 px ;
- aucun débordement horizontal en 390 px ;
- lien de téléchargement réel : `telechargements/DIOPTRE-Setup-2.5.3.exe`,
  servi en `application/x-msdownload`, 2 143 505 octets, empreinte SHA-256
  `7f35ac92…` vérifiée après téléchargement ;
- page testée servie par un hébergement réel : HTTP 200, aucun 404, aucune
  erreur JavaScript en console.

## Ce que je veux faire auditer

1. **Sécurité** : injection HTML dans les textes statiques, comportement du
   petit script de thème (lecture/écriture `localStorage`, aucune donnée
   sensible), en-têtes HTTP de l'hébergeur (CSP absente, HSTS, `X-Content-Type`).
2. **Accessibilité** : contrastes des deux thèmes, navigation au clavier,
   structure des titres, alternatives textuelles des images.
3. **Performance** : page de 368 Ko avec images intégrées — est-ce le bon
   compromis face à quatre requêtes séparées ? (le choix vient d'un 429 de
   l'hébergeur sur des requêtes parallèles).
4. **SEO et partage** : `canonical`, Open Graph, `sitemap.xml`, `robots.txt`,
   aperçu de lien.
5. **Cohérence** : le texte annonce « Python 3.14 requis » et un installateur
   non signé — est-ce assez clair pour un visiteur non technique ?

## Limites connues

- Aucun HTTPS propre au site : le certificat est celui de l'hébergeur o2switch.
- L'installateur n'est pas signé : Windows affiche un avertissement SmartScreen.
- Pas de page de mentions légales ni de politique de confidentialité.
- Le site ne contient aucune donnée dynamique : il n'y a pas de formulaire,
  donc pas de surface d'injection côté serveur.
