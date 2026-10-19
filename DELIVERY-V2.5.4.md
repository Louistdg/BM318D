# Livraison V2.5.4 — corrections de l'audit

Date : 19/10/2026. Base : tag v2.5.3, audit externe du 19/10.

## Corrigé

1. **Noms de modèles Ollama échappés** dans `BM318d-Railway.html`
   (`chargerModeles`) : `escapeHtml` sur la valeur et le texte de l'option.
2. **Manifeste ZIP borné** dans `mc_documents.restore_imports` : taille
   déclarée vérifiée avant décompression, puis lecture en flux limitée à 8 Mio.

## Non retenu

- Le constat « `storage_path` non échappé » ne se vérifie pas : la valeur est
  déjà dans `safe(...)`. Preuve dans `AUDIT/03-REPONSES-AU-RAPPORT.md`.

## Documentation corrigée

- Le bac à sable réel est WSL + bubblewrap + seccomp ; le backend Windows natif
  est refusé par le code. README, `AUDIT/00` et `AUDIT/01` disent maintenant la
  même chose que le code.
- `MC_SANDBOX` est un dossier, pas un interrupteur.
- « Bibliothèque standard uniquement » est précisé : exception MCP, verrouillée
  volontairement par des noms de paquets inexistants.

## Vérification

- `test_documents.py` : 18 tests, dont deux nouveaux de non-régression.
- `test_all.cmd` : 12 étapes.
