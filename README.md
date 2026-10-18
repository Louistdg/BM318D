# BM318D — Control Center

BM318D is a local-first Windows control center for organizing projects, AI agents, missions, assignments, and their evidence. The repository contains the Python desktop/server application, the Mission Control web interface, AI-provider and MCP connector code, security/sandbox modules, installer scripts, and automated tests.

## Project at a glance

- **Desktop and local service:** Python/Tkinter entry points and a local Mission Control HTTP service.
- **Mission Control UI:** project agents and teams, missions and assignments, a visual canvas, context and handoffs, jobs, plans, reviews, and evidence.
- **AI support:** local Ollama and compatible provider integrations, per-agent assignments, quotas/fallback behavior, and connector management.
- **Security work:** route authorization, isolated workspaces, sandbox backends, permission checks, and tests.

This repository is a reviewed source snapshot, not a deployment package. Local databases, credentials, backups, logs, and personal handoff notes are intentionally excluded. Do not add them to Git.

## Start here

1. Read this file and [`docs/SECURITY-STATUS.md`](docs/SECURITY-STATUS.md).
2. Read [`MISSION-CONTROL-LISEZMOI.txt`](MISSION-CONTROL-LISEZMOI.txt) for the product flows described by the project.
3. Read [`GROK-MISSION-01-PRODUCT-AUDIT.md`](GROK-MISSION-01-PRODUCT-AUDIT.md) for the initial read-only design and interaction review.
4. The principal UI files are `BM318d-Railway.html`, `mission.js`, `mission.css`, and `connectors.js`; server behavior is implemented mainly in `MissionControl.py`, `BM318d-WebServer.py`, `mc_agent.py`, and `mc_connectors.py`.

## Local development

Use a disposable copy and temporary databases for tests. Review the command and environment before running scripts; do not point tests at a real user database or a live service. The individual test files document their fixtures and can be run with Python or Node where applicable.

## Collaboration

The initial discovery review is recorded in `GROK-MISSION-01-PRODUCT-AUDIT.md`. Implementation now proceeds on feature branches with pull requests and test evidence. See [`docs/DELIVERY-V24.md`](docs/DELIVERY-V24.md) for the integrated changes, verification and local installation model.

## Parcours

The project canvas is the home screen and preserves existing task positions and dependencies. The overview uses the real project tasks and registered agents; Mission Control remains available in the application navigation. Both Railway launchers start the authenticated local service (port 31880).

`OUVRIR-BM318d.cmd` only opens a local `index.html` export when that file exists beside the scripts. It does not start the service. The other `LANCER-*.cmd` files still open the older desktop windows (Studio, Unifié, Extensions, `BM318d.pyw`).

## Imported project files

Imported files are copied into the selected project's local workspace, under `p<project-id>/fichiers-importes/`; the selected folder structure is reflected below that directory. The original file is left in place. Notes and file metadata remain in SQLite, but SQLite backups do **not** include the copied file contents. Include each project's configured workspace folder in the user's regular file backups. Removing an imported-file card from the interface currently removes only its BM318d record, not the physical file.
