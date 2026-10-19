# Résultat de l'audit — 19/10/2026

## Passe 1 (2.5.3) — 3 constats faibles

| Constat | Suite |
|---|---|
| Faible 1 — noms de modèles Ollama non échappés | **corrigé** en 2.5.4, confirmé |
| Faible 2 — manifeste ZIP lu avant contrôle de taille | **corrigé** en 2.5.4, confirmé |
| Faible 3 — `storage_path` non échappé | **retiré par l'auditeur**, erreur de lecture de sa part |

## Passe 2 (2.5.4) — verdict

> « Les deux corrections sont réelles et testées, le troisième constat est retiré,
> la documentation correspond maintenant au code, et la chaîne Git ↔ paquet fermé
> ↔ vitrine est close pour la 2.5.4. Le rapport 2.5.3 est soldé : 0 constat en
> attente de correction. »

Ce que l'auditeur a vérifié lui-même :

- `chargerModeles()` : `escapeHtml` sur la valeur et le texte de l'option ;
- `restore_imports` : `ZipInfo.file_size` contrôlé avant décompression, lecture
  plafonnée à 8 Mio + 1 ;
- les deux tests de non-régression présents et passants (18/18 sur `test_documents.py`) ;
- documentation du bac à sable conforme au code (WSL + bubblewrap + seccomp) ;
- `MC_SANDBOX` décrit comme un dossier ;
- verrou `httpx2` / `httpcore2` assumé par écrit ;
- `test_http.py` 40/40, pas de régression sur `test_securite.py` ;
- installateur de la vitrine : 2 143 732 octets, SHA-256 `229b3682…`, identique au paquet ;
- paquet fermé : 129 fichiers, 129 empreintes conformes, source identique au tag.

## Ce qui reste ouvert, sans surface d'attaque

- `mc_security.operator()` ignore ses paramètres `expected*` (signature trompeuse) ;
- scripts `patch_*.py` / `fix_*.py` encore à la racine ;
- corbeille jamais purgée ;
- `storage_root` absolu non suivi si `workspace_dir` change ;
- bac à sable WSL non testé dynamiquement sur le poste réel ;
- dépôt public.

## Portée de ce verdict

L'audit porte sur la **2.5.4**. La **2.6.0** est postérieure : renommage complet
(fichiers, lanceurs, base `dioptre.sqlite3` avec reprise automatique), aucun
changement de logique de sécurité. Une passe de confirmation sur 2.6.0 reste à
demander si elle est jugée nécessaire.
