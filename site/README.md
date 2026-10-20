# Le site (vitrine)

Ce dossier contient la source exacte de la vitrine publique :

    https://dioptre.socle-construction.be

## Fichiers

```
index.html        page d'accueil : présentation, fonctions, captures, téléchargement
installation.html guide d'installation en quatre étapes + questions courantes
favicon.svg       icône du site
robots.txt        indexation autorisée, sitemap déclaré
sitemap.xml       deux URL : / et /installation.html
assets/02-mission-control.jpg   image de partage (og:image)
```

L'installateur Windows (`DIOPTRE-Setup-2.5.4.exe`, 2 Mo) n'est pas versionné :
un binaire de cette taille n'a pas sa place dans Git. Il est publié sur le
serveur, dans `telechargements/`, et reconstruit par `installer/DIOPTRE.iss`.

Empreinte publiee sur la page d'accueil :

    DIOPTRE-Setup-2.5.4.exe   2 143 732 octets
    SHA-256 229b368253e48eb18a96a8eee834097a5ef6df1d3f273d89b69bb3c1f6188f9a

## Comment le site est construit

- 100 % statique : HTML, CSS et un peu de JavaScript inline. Aucun build.
- Aucune requête externe : les quatre captures de l'application sont intégrées
  dans `index.html` en data URI. Un seul appel réseau pour toute la page.
- Deux thèmes : **Sable** par défaut (gris neutre, texte blanc chaud), **Nuit**
  en option (violet sombre). Le choix est mémorisé dans `localStorage`
  (clé `tredio-theme`).
- Aucun traceur, aucun cookie, aucune statistique.

## Comment le publier

Le serveur est un hébergement o2switch, dossier `public_html/dioptre`.

```powershell
$env:O2_FTP_USER = "compte-ftp"
$env:O2_FTP_PASS = "mot-de-passe"
powershell -File D:\MIGRATION-2026\DIOPTRE\upload-dioptre.ps1 -FichierAcces ...
```

Le script envoie les fichiers, les relit et compare les empreintes SHA-256.
Détail mesuré : le certificat TLS du serveur FTP couvre `sapin.o2switch.net`,
pas `ftp.socle-construction.be` — d'où l'hôte par défaut du script.

## Ce qui n'est pas ici

- l'installateur (binaire, voir plus haut) ;
- les captures d'écran de contrôle, conservées dans `D:\MIGRATION-2026\DIOPTRE\captures\` ;
- les journaux de publication.
