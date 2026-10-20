# TREDIO

**Version 2.5.4 — 19/10/2026.** Ancien nom : **DIOPTRE**. Les chemins de données et le coffre historique restent compatibles.
Ce depot contient la source complete de l'application Windows : service Python
local, interface Mission Control, connecteurs IA, bac a sable, tests.

Tredio is a local-first Windows control center for organizing projects, AI agents,
missions, assignments, and their evidence. The repository contains the Python
desktop/server application, the Mission Control web interface, AI-provider and MCP
connector code, security/sandbox modules, installer scripts, and automated tests.

## Project at a glance

- **Desktop and local service:** Python/Tkinter entry points and a local Mission Control HTTP service.
- **Mission Control UI:** project agents and teams, missions and assignments, a visual canvas, context and handoffs, jobs, plans, reviews, and evidence.
- **AI support:** local Ollama and compatible provider integrations, per-agent assignments, quotas/fallback behavior, and connector management.
- **Security work:** route authorization, isolated workspaces, sandbox backends, permission checks, and tests.

## Audit status

Audited externally on 19/10/2026 (static review + dynamic tests on an isolated
server). Report closed with **0 open findings**: two weak points fixed in 2.5.4
(Ollama model names now escaped, ZIP manifest size bounded), one withdrawn by
the auditor. Details: `AUDIT/04-RESULTAT-AUDIT-2.5.4.md`.

## Audit pack

`AUDIT/00-LIRE-EN-PREMIER.md` describes what to audit, by priority, and lists the
known limitations so they are not reported as findings.
`AUDIT/01-COMMENT-TESTER.md` gives the exact commands and expected results.
`AUDIT/02-AUDIT-DU-SITE.md` covers the public website.

## Repository layout

```
MissionControl.py      service HTTP local et routes
mc_*.py                securite, bac a sable, connecteurs, documents, agents, plan
*.js / *.css           interface Mission Control
test_*.py              suite de tests (25 fichiers), lancee par test_all.cmd
installer/             installateur Windows (Inno Setup)
site/                  source de la vitrine publique (statique)
AUDIT/                 brief d'audit, commandes de test, audit du site
```

## Version history (recent)

- **2.5.3** — explicit revision errors, deleted documents moved to a `corbeille`
  folder, backups timestamped to the microsecond.
- **2.5.2** — restoring over a locally modified file now answers **HTTP 409**
  with a JSON message instead of dropping the connection.
- **2.5.1** — import/restore of documents with a ZIP archive of uploaded files.

## Security model, in one screen

- session token in an HttpOnly cookie plus `X-MC-Token` header;
- separate administrator token (`X-MC-Admin`) for sensitive routes;
- host and origin checks, body size and rate limits;
- job execution goes through `mc_sandbox.py`, which refuses any unrestricted
  fallback: under Windows it transports to **WSL**, where isolation is
  **bubblewrap + seccomp + namespaces** (`mc_sandbox_linux.py`). The native
  Windows backend is explicitly refused as unvalidated;
- MCP discovery locked by default.

Known limits: isolation requires WSL on Windows, file reads outside the
workspace are not confined, the sandboxed child network is not filtered by the
application, SQLite is single-file.

The stdlib-only claim covers the server, the interface, the database, documents
and security. MCP discovery is the one exception: it imports `mcp`, and
deliberately `httpx2` / `httpcore2`, which do not exist publicly. That is a lock,
not a dependency: discovery fails closed instead of opening by accident.

## Quick start

```cmd
set MC_DB=%TEMP%\dioptre.sqlite3
C:\Python314\python.exe MissionControl.py
```

Then open http://127.0.0.1:31880/ — the session token is in the page, the
administrator token is written next to the database in `logs/admin-token.txt`.

This repository is a reviewed source snapshot, not a deployment package. Local
databases, credentials, backups, logs, and personal handoff notes are
intentionally excluded. Do not add them to Git.
