# BM318d V2.5.1 — correctifs issus de l’audit

## Changements livrés dans cette branche

- Une base neuve crée les tables historiques du canevas et un premier projet; une base existante garde ses lignes. Une sauvegarde demandée quand aucune base n’existe ne crée plus un fichier SQLite vide.
- Un contrôle `py_compile` ou `node_check` doit nommer un fichier présent dans le workspace. `unittest` exige des fichiers de tests et un résultat qui confirme qu’au moins un test a été exécuté. La validation demande aussi une revue du code et une revue humaine des résultats de tests; la page affiche une action explicite pour cette revue.
- Le chat accepte un corps plus grand que 16 Ko, sans couper silencieusement le prompt, et transmet les douze derniers messages de la conversation à Ollama. Les réponses peuvent aller jusqu’à 1 200 tokens.
- Le budget de sortie par défaut des jobs passe à 4 000 tokens et reste borné entre 128 et 8 192.
- Les limites HTTP sont désormais par identité et par route; les actions sensibles ont un plafond distinct. Les routes d’arrêt, de consultation des sauvegardes et de révocation ne nécessitent pas de projet sélectionné.
- La revue automatique signale aussi quelques motifs JavaScript risqués; elle est toujours un filtre de motifs, pas une analyse complète.
- L’aperçu ne fabrique plus quatre agents : il charge ceux du projet et affiche explicitement quand il n’y en a pas. Le README présente le canevas comme écran d’accueil.
- L’installateur copie les fichiers Documents et Workspace manquants, crée les sous-dossiers nécessaires et annonce la version 2.5.1.

## Preuves locales

Tests exécutés sur des bases et dossiers temporaires, sauf les tests Windows de connecteurs qui créent leur propre base temporaire :

- `test_clean_install.py` : installation propre et persistance — PASS.
- `test_jobs.py` : 53 réussis, 0 échec.
- `test_review.py` : 21 réussis, 0 échec.
- `test_http.py` : 38 réussis, 0 échec.
- `test_app.py` : 43 réussis, 0 échec, y compris l’installateur sur cible temporaire.
- `test_connectors.py` : 12 réussis, 0 échec.
- `test_securite.py` : 67 réussis, 0 échec.
- Interfaces : `test_ui.mjs` 55/55, `test_chat_ui.mjs` 19/19, `test_connectors_ui.mjs` 16/16, `test_security_ui_v23.mjs` 11/11; contrat d’interface et en-têtes de sécurité PASS.
- WSL 2, distribution Ubuntu, utilisateur `louis` (UID 1000, pas root), bubblewrap : `test_sandbox_v23.py` 26/26. Les contrôles OS refusent notamment les lectures hors workspace, `/mnt/c`, `/mnt/d`, le réseau, les sous-processus et la transmission d’un secret d’environnement.
- Suites complémentaires : équipes 30/30, plans 28/28, branches 20/20, ainsi que preuves exactes, permissions, arrêt honnête, documents, projets conservés, sauvegarde/restauration, mémoire, contexte et support — PASS.

`test_connectors_securite.py` : 27 tests, 1 ignoré faute de jeton administrateur de la machine, 0 échec. Aucune suite n’a utilisé le service actif ou la base de production.

## Limites restantes de l’audit

- Une revue humaine confirme que les tests exécutés correspondent au changement, mais l’application ne peut pas démontrer automatiquement qu’un test écrit dans le workspace est pertinent ou indépendant. La sortie « test vert » reste un élément de preuve, pas une preuve mathématique.
- Il n’existe toujours pas de flux d’import/export d’un dépôt réel dans un job.
- L’ancienne API canevas et Mission Control restent dans le même processus et partagent la base; leur séparation est un chantier architectural.
- Les réglages Ollama présentés par projet peuvent encore affecter des éléments globaux du processus.
- Les jetons administrateur et la sauvegarde des workspaces demandent encore une refonte; les sauvegardes automatiques existantes ne doivent pas être supprimées ou remplacées.
- Les permissions des agents recrutés restent fermées tant qu’elles ne sont pas configurées; les agents créés manuellement ont encore les permissions historiques par défaut.
- Le correctif est destiné au déploiement local de prévisualisation. Il ne constitue pas une certification de sécurité ni une preuve d’installation sur une machine vierge. MCP reste verrouillé.
