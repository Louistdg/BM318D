# BM318D — Livraison V2.5.1 : consolidation A1–A4 et vérification B1

**Date du rapport :** 18 octobre 2026

**Dépôt :** [Louistdg/BM318D](https://github.com/Louistdg/BM318D)

**Branche de livraison :** [`codex/v25-import-fichiers`](https://github.com/Louistdg/BM318D/tree/codex/v25-import-fichiers)

**Base de travail :** `codex/v25-railway-workspace` (V2.5.1, `c7f6bec`)

**Périmètre :** travail local sous Windows ; aucune fusion vers `main`, aucun déploiement en production.

## État des priorités

| Priorité | Résultat vérifié | Fichiers principaux | Commits |
| --- | --- | --- | --- |
| **A1 — Sauvegardes des imports** | Chaque sauvegarde SQLite normale produit une archive associée `.imports.zip` pour les fichiers importés. La restauration récupère les fichiers absents et refuse d'écraser un fichier local différent. La rotation supprime aussi les archives associées aux sauvegardes automatiques expirées. | `MissionControl.py`, `mc_documents.py`, `test_documents.py`, `test_app.py`, `README.md` | `efe2217`, `4c86129` |
| **A2 — Nettoyage Windows** | Fermeture explicite des connexions SQLite du serveur historique et de la sauvegarde ; le test Mission Control se termine sans l'erreur de nettoyage Windows précédemment reproduite. | `BM318d-WebServer.py`, `MissionControl.py`, `test_support_v23.py` | `ad720c6` |
| **A3 — Preuves de tests** | Reproduction d'un `unittest` factice avec `assert True`, puis refus de validation quand la proposition ne contient aucune source livrée hors fichiers de tests. La revue humaine des tests reste obligatoire. | `MissionControl.py`, `test_review.py`, `test_ui.mjs` | `24325be`, `134122d` |
| **A4 — Prompt du chat** | Les deux serveurs acceptent un corps JSON jusqu'à 2 Mio sur `/api/ollama` ; le test HTTP prouve le transport de 120 000 caractères Unicode et le refus explicite de 120 001 caractères. | `BM318d-WebServer.py`, `MissionControl.py`, `test_http.py` | `cf816f2` |
| **B1 — Installateur** | Vérification du manifeste `2.5.1`, des fichiers indispensables copiés et du démarrage sur base temporaire. Les correctifs de manifeste existaient déjà sur la branche V2.5.1 de départ : **pas de nouveau commit B1**. | `installer/BM318d-Setup.ps1`, `installer/version.json`, `test_app.py`, `test_clean_install.py` | Déjà présent dans `c7f6bec` |

### Historique préalable conservé

- `33e541d` — `corrige la syntaxe du script historique` : un ancien script empêchait `compileall` de réussir.
- `afa4059` — `conserve le travail local sur les imports` : enregistrement des modifications locales antérieures sur la branche isolée.
- Aucun test existant n'a été supprimé pour faire passer les changements.

## Reproduire les vérifications

Exécuter depuis la **racine du dépôt**, avec Python et Node.js installés. Les contrôles cités ci-dessous ont été exécutés sous **Windows avec Python 3.15.0 et Node.js 24.21.0** ; il ne s'agit **pas** de versions minimales officiellement établies. Les tests démarrent leurs propres services et utilisent des bases temporaires ; ne pas les rediriger vers une base de production via `MC_DB`.

```powershell
python -m compileall -q .
git diff --check
python -m unittest -q test_documents
python test_app.py
python test_http.py
python test_jobs.py
python test_review.py
python test_clean_install.py
python test_securite.py
node test_interface_contrat.mjs
node test_chat_ui.mjs
node test_ui.mjs
```

**Résultats observés lors de la reprise et de la clôture :**

| Contrôle | Résultat |
| --- | --- |
| Documents | 13 tests réussis |
| Application, installateur et rotation | 44 tests réussis |
| HTTP / taille du prompt | 40 tests réussis |
| Jobs | 53 tests réussis |
| Revue, validation et faux test | 23 tests réussis |
| Installation propre sur base temporaire | `CLEAN_INSTALL_OK` |
| Sécurité | 67 tests réussis |
| Contrat d'interface | `ok contrat interface` |
| Chat UI | 19 tests réussis |
| Interface Chrome (exécution séparée) | 71 tests réussis, 0 échec |
| Compilation Python et `git diff --check` | Réussis |

**Attention :** ces tests sont hétérogènes (scripts exécutables et tests `unittest`). La commande générique `python -m unittest discover -s . -p "test_*.py"` n'est pas le protocole de validation retenu pour cette livraison : utiliser les commandes testées ci-dessus.

## Limites, risques et conditions de reprise

1. **Sauvegarde à deux fichiers :** conserver ensemble `nom.sqlite3` et `nom.imports.zip`. Une ancienne sauvegarde dépourvue de ZIP ne permet pas de récupérer les imports disparus. Une sauvegarde normale signale l'absence d'un fichier importé au lieu d'affirmer qu'elle l'a archivé.
2. **Restauration prudente :** un fichier local existant mais différent bloque la restauration des imports plutôt que d'être écrasé. La sauvegarde de sécurité créée juste avant restauration porte sur SQLite uniquement, afin de rester possible lorsque les imports ont déjà été perdus.
3. **Pertinence des tests :** le cas « un fichier `test_foo.py` contenant seulement `assert True` » est bloqué à la validation. Cela ne démontre pas la pertinence de toutes les suites de tests ; les revues de code et des tests restent nécessaires.
4. **Installateur :** installation temporaire vérifiée, mais pas de validation sur une machine Windows entièrement vierge ni de distribution utilisateur finale.
5. **Ollama :** contrôle du chemin HTTP et des limites de caractères, pas de preuve d'une réponse réelle d'Ollama à un prompt de 120 000 caractères.
6. **Sécurité :** ne pas affaiblir les sandboxes, les protections SSRF, le contrôle Host/Origin, ni la séquence proposition → approbation → test → validation → commit. L'exécution MCP reste verrouillée.

## Livraison et suites possibles

La branche dédiée est distincte de `main` et n'a pas été fusionnée. Pour une future itération, créer une **nouvelle branche** à partir de cette livraison et faire relire les changements avant toute intégration.

Travaux ultérieurs possibles, **hors du périmètre livré** : runner CI Windows/Linux et tests Chrome, installation sur Windows vierge, amélioration de la couverture contre les tests non pertinents et suite de la liste de priorités B. Ces points ne sont **pas** déclarés réalisés dans ce document.
