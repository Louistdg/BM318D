# Réponses au rapport d'audit du 19/10/2026

Référence auditée : `main` @ 35a1c39 et tag `v2.5.3`.
Cette note dit ce qui a été corrigé, ce qui ne l'a pas été et pourquoi, et
répond aux questions laissées ouvertes.

## Constats faibles

### Faible 1 — noms de modèles Ollama non échappés — **corrigé**

`DIOPTRE.html`, `chargerModeles()` : les noms passent maintenant par
`escapeHtml` sur la valeur **et** sur le texte de l'option.

```js
sel.innerHTML = modeles.map(m => '<option value="' + escapeHtml(m) + '">' + escapeHtml(m) + '</option>').join('')
```

Non-régression : `test_model_names_are_escaped_in_the_page` dans
`test_documents.py` vérifie que la construction non échappée ne réapparaît pas.

### Faible 2 — manifeste ZIP lu avant contrôle de taille — **corrigé**

`mc_documents.restore_imports` vérifie désormais `ZipInfo.file_size` **avant**
toute décompression, puis lit en flux borné à 8 Mio + 1 octet et refuse
au-delà. Une archive dont le manifeste ferait plusieurs gigaoctets est rejetée
sans être gonflée en mémoire.

Non-régression : `test_huge_manifest_is_refused_before_reading` fabrique un ZIP
dont le manifeste déclare 9 Mio et vérifie le refus.

### Faible 3 — `storage_path` non échappé dans l'interface — **non retenu**

Le constat ne se vérifie pas sur le code livré. La valeur est bien à
l'intérieur de `safe(...)` :

```js
<p>'+safe(x.kind==='folder'?'Ouvrir pour consulter':x.storage_path?x.storage_path:x.content.slice(0,115))+'</p>
```

La parenthèse de `safe(` englobe toute l'expression ternaire. Vérification
exécutée avec l'implémentation réelle de `safe` extraite de `workspace.js` :

```
entree  : <img src=x onerror=alert(1)>.txt
sortie  : &lt;img src=x onerror=alert(1)&gt;.txt
echappe : true
```

La validation amont de `storage_path` reste en place ; elle n'est pas la seule
défense. Aucune modification de code n'a donc été faite pour ce point.

## Écarts documentation / code

### 1. Le bac à sable annoncé n'est pas celui du code — **corrigé dans la doc**

Le README et le brief parlaient d'un bac à sable Windows natif (jeton restreint,
intégrité basse, objet job). Le code livré refuse explicitement ce backend
(`mc_sandbox.py`, « backend Windows natif expérimental non validé ») et exécute
via WSL + bubblewrap + seccomp.

La documentation décrit maintenant le modèle réel : transport WSL sous Windows,
isolation bwrap + seccomp + namespaces sous Linux, refus explicite du backend
Windows natif.

### 2. `MC_SANDBOX` présenté comme un interrupteur — **corrigé dans la doc**

La variable désigne le **dossier** du bac à sable. La sélection du backend se
fait par `MC_SANDBOX_BACKEND`. La ligne fautive de `AUDIT/01-COMMENT-TESTER.md`
est remplacée.

### 3. « Bibliothèque standard uniquement » — **précisé**

Vrai pour tout le socle (serveur, interface, base, documents, sécurité).
Faux pour la découverte MCP, qui importe `mcp`, `httpx2` et `httpcore2`.
Ces deux derniers noms n'existent pas publiquement : c'est un **verrou
volontaire**, la découverte MCP échoue donc proprement au lieu de s'ouvrir.
C'est désormais écrit tel quel dans le README.

## Réponses aux questions laissées ouvertes

- **Le backend Windows natif existe-t-il ailleurs ?** Non dans ce dépôt. Il a
  existé sous forme de prototype, retiré parce que non validable : le refus est
  délibéré, pas un oubli. Le backend réel est WSL + bwrap.
- **`httpx2` / `httpcore2` : paquets réels ?** Non. Verrou volontaire pour que
  la découverte MCP ne s'active pas par accident.
- **La corbeille est-elle purgée ?** Non. Elle grandit sans limite. Ce n'est pas
  un oubli de sécurité mais une dette assumée : la purge demande une politique
  de rétention (durée, taille, confirmation) que le produit n'a pas encore.
- **Que se passe-t-il si `workspace_dir` change après des imports ?** Les
  `storage_root` absolus enregistrés en base ne suivent pas. Les fichiers
  restent accessibles à leur ancien emplacement ; la sauvegarde les référence
  toujours. Aucun déplacement automatique n'est fait.

## Points de qualité signalés, non corrigés dans cette version

- `mc_security.operator(session, expected, admin, expected_admin)` ignore ses
  deux paramètres `expected*` et utilise la configuration globale. Le
  comportement est sûr (aucun appel ne peut imposer un jeton), mais la signature
  est trompeuse.
- Scripts de développement `patch_*.py`, `fix_*.py` encore à la racine.
- Duplication du routeur GET/POST historique.
- Threads de jobs non bornés en dehors du limiteur de débit.

Ils sont identifiés, non corrigés, et ne changent pas la surface d'attaque
décrite par l'audit.
