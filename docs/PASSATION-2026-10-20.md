# Reprise — DIOPTRE 2.8.4

Dernière mise à jour : 20 octobre 2026, 00:55.
Poste redémarré proprement le 20/10 à 00:40. Tout est sur le disque.

---

## 1. État en une minute

| Quoi | État |
|---|---|
| Service local | **2.8.4**, démarré automatiquement au login, HTTP 200 sur le port 31880 |
| Base | `D:\DIOPTRE-Control-Center\bm318d.sqlite3` (188 416 o) |
| Site | `dioptre.socle-construction.be` en 2.8.4, mascotte dans le pied de page |
| Installateur | `DIOPTRE-Setup-2.8.4.exe`, 2 150 541 o |
| Paquet d'audit | `DIOPTRE-AUDIT-2.8.4.zip`, 4 038 486 o, 151 fichiers |
| Dépôt | `Louistdg/DIOPTRE`, tag `v2.8.4`, branche `main` à jour, travail propre |
| Sauvegarde hors disque | quotidienne 19:00 vers OneDrive, 2 copies présentes |
| Démarrage auto | raccourci dans le dossier Démarrage, testé |
| Réouverture des apps au redémarrage | désactivée (`RestartApps=0`) |
| Worktrees | 4/4 sains, pointeurs réparés |

---

## 2. Les liens

| Quoi | Lien |
|---|---|
| Vitrine | https://dioptre.socle-construction.be |
| Guide d'installation | https://dioptre.socle-construction.be/installation.html |
| Installateur | https://dioptre.socle-construction.be/telechargements/DIOPTRE-Setup-2.8.4.exe |
| Dépôt | https://github.com/Louistdg/DIOPTRE |
| Version 2.8.4 | https://github.com/Louistdg/DIOPTRE/releases/tag/v2.8.4 |
| Site principal | https://socle-construction.be |
| Notion — page Dioptre | https://app.notion.com/p/Dioptre-3fe8179d38e88151ae11e8f719209b18 |

Empreintes affichées en page d'accueil :

```
installateur  3bcd22fc9d34a20c76e001f0a46119c851fe5eda683ab098793b09ffa1f7daa2
paquet audit  93d0b10dfc82f1e4deae58322fd71647b039e69290a105d116410a067e3c9c33
```

---

## 3. Les chemins sur le disque

```
D:\DIOPTRE-Control-Center\          base, sauvegardes automatiques
D:\DIOPTRE-Supervision\             scripts, journaux, dist des versions
D:\DIOPTRE-Supervision\demarrer-service.cmd      lancement Ollama + DIOPTRE
D:\DIOPTRE-Supervision\sauvegarde-externe.ps1    copie vers OneDrive
D:\DIOPTRE-Supervision\redemarrage-propre.ps1    fermeture + redémarrage
D:\DIOPTRE-worktrees\codex-v24-delivery\         dépôt de travail
D:\DIOPTRE-releases\                 releases préparées
D:\DIOPTRE-delivery-evidence\        preuves de livraison
D:\MIGRATION-2026\BM318D\installateur\           sources Inno Setup
D:\MIGRATION-2026\BM318D\deploy\                 copie locale du site publié
D:\MIGRATION-2026\BM318D\AUDIT\DIOPTRE-AUDIT-2.8.4\      dossier à envoyer
D:\MIGRATION-2026\BM318D\AUDIT\DIOPTRE-AUDIT-2.8.4.zip   archive à envoyer
D:\MIGRATION-2026\BM318D\outils\                 scripts Notion, mascotte
```

Application installée : `C:\Users\louis\AppData\Local\DIOPTRE\`

---

## 4. Le code, en un tableau

```
MissionControl.py   593 lignes   serveur HTTP, contrôles, point d'entrée
mc_jobs.py          324         jobs : proposition, preuve, revue, validation
mc_agents.py        292         agents, rôles, permissions, branches, plans
mc_legacy.py        239         les neuf routes historiques
mc_missions.py      228         missions, affectations, notes, messages
mc_backups.py        99         sauvegarde, restauration, rotation
mc_corbeille.py      99         purge de la corbeille (30 jours)
mc_routes.py         72         table des 44 routes
mc_store.py          71         réglages, recherche, notifications
mc_actions.py        34         décorateur @action
```

MissionControl.py : 1 340 → 593 lignes. `_dispatch` : 94 → 11 lignes.
`_guard_function` supprimé. Aucun chargement dynamique. Aucun `CREATE TABLE`
à l'import. Le second serveur non authentifié n'existe plus.

---

## 5. Vérifier que tout va bien (2 minutes)

```powershell
# service
(Invoke-WebRequest http://127.0.0.1:31880/ -UseBasicParsing).StatusCode   # 200

# version
$r = Invoke-WebRequest http://127.0.0.1:31880/ -UseBasicParsing
$t = [regex]::Match($r.Content,'name="mc-token" content="([^"]+)"').Groups[1].Value
(Invoke-WebRequest 'http://127.0.0.1:31880/api/mc/version' -Headers @{'X-MC-Token'=$t} -UseBasicParsing).Content

# suite de tests complète
cd D:\DIOPTRE-worktrees\codex-v24-delivery
cmd /c test_all.cmd
```

Dernier résultat connu : **SUCCES, 71 ok**. Tests du bac à sable WSL : 7/7.

---

## 6. Ce qui reste à faire

1. **Notion en 2.8.4** — la page est encore en 2.8.3. Le CLI a perdu son jeton.
   À faire dans un terminal WSL :
   ```bash
   NOTION_KEYRING=0 ntn login
   bash /mnt/d/MIGRATION-2026/BM318D/outils/maj-notion-dioptre.sh
   ```
   `NOTION_KEYRING=0` est important : le jeton s'écrit dans un fichier et
   survit aux sessions, au lieu du trousseau qui ne vit que dans un terminal.

2. **Envoyer le paquet d'audit** :
   `D:\MIGRATION-2026\BM318D\AUDIT\DIOPTRE-AUDIT-2.8.4.zip`

3. **Captures du site en 2.8.4** — les captures actuelles datent de 2.5.3.
   L'interface n'a pas changé, mais la version affichée si.

4. **Reprise éventuelle** : l'auditeur demandera peut-être des précisions sur
   le bac à sable ; les preuves sont dans le paquet (`06-BAC-A-SABLE.txt`).

---

## 7. Points ouverts connus (assumés)

- `mission.js` fait encore ~1 600 lignes, non découpé.
- La purge de la corbeille est best-effort : un fichier verrouillé est ignoré.
- L'installateur n'est pas signé (Windows affiche un avertissement).
- Le dépôt est public.
- Trois worktrees `v23-*` ont été réparés mais restent des branches anciennes.

---

## 8. Historique de la session (19 → 20 octobre)

```
2.6.0  renommage BM318D -> DIOPTRE
2.6.1  reprises (coffre, sauvegardes)
2.6.2  coffre : clé absente vs panne
2.7.0  mode démonstration
2.8.0  démontage du serveur historique, modules séparés
2.8.1  purge de la corbeille
2.8.2  mc_agents.py, operator() explicite
2.8.3  mc_store.py, découpage terminé
2.8.4  bac à sable WSL testé, racines suivies, outils-dev/
```

---

## 9. En cas de problème

- Service absent : double-clic `D:\DIOPTRE-Supervision\demarrer-service.vbs`,
  ou relancer la session Windows.
- Base suspecte : les sauvegardes sont dans `D:\DIOPTRE-Control-Center\backups\`
  et dans `C:\Users\louis\OneDrive\DIOPTRE\sauvegardes\`.
- Site cassé : la copie locale est dans `D:\MIGRATION-2026\BM318D\deploy\`,
  publication par `upload-dioptre.ps1` (mode Simulation d'abord).
