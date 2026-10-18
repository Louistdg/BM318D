# V2.4 integration and verification

Integrated Grok's UX/security branch through `9cef6f7`, including the responsive
stage-height correction. Codex added two final corrections:

- Desktop stop and backup resolve a real positive project ID. Unavailable,
  empty or malformed project state refuses the action before any POST. The new
  HTTP regression test reproduced seven failing cases before the fix and passes
  afterwards. Valid project 7 is preserved in both desktop clients.
- Mission Control uses its own toolbar. Legacy task actions stay in the legacy
  views. Connectors are accessible through Compte without a floating button
  covering the mini-map. Empty-team guidance wraps inside the viewport; unused
  map controls are hidden until agents exist.

## Fresh verification

All tests used isolated code copies and temporary databases.

| Environment | Check | Result |
| --- | --- | --- |
| Windows | Desktop project regression | 4 test methods, all cases pass |
| Windows / Python 3.14 | Real HTTP stop and backup | 20 checks pass |
| Windows / Chrome | Main UI | 53 pass |
| Windows / Chrome | Connectors / chat / security UI | 16 / 17 / 11 pass |
| Windows / Node | Header security / interface contract | 7 pass / pass |
| Windows | Connector integration | 12 pass |
| Windows | Connector security | 27 run, 1 skipped |
| Windows | HTTP / Mission Control | 37 pass / PASS |
| WSL 2, ordinary UID 1000, Bubblewrap 0.11.1 | Security including OS confinement | 67 pass (including 26 sandbox cases) |
| Same WSL environment | Jobs / reviews | 50 / 19 pass |
| Same WSL environment | Desktop project / evidence / preserved data | pass / 8 pass / pass |

The sandbox checks deny outside reads including Windows drive mounts, socket
operations, subprocess creation and namespace escape; they also check child
environment cleanup and parent-death termination. WSL by itself still exposes
Windows mounts to its user and is not the isolation boundary. Bubblewrap,
namespaces, seccomp and the runtime restrictions provide confinement.

The connector security suite skips the test requiring an existing host admin
token. A legacy Windows test reports a temporary SQLite cleanup lock at process
exit despite passing its assertions; that cleanup warning remains. UI model
selection checks are skipped when no local Ollama model is available. Paid
provider calls have not been exercised. MCP execution remains locked.

## Local installation

The deployed runtime lives in a versioned release directory. Existing dirty
source trees remain intact. `MC_DB` and `MC_WORKSPACES` point explicitly to the
existing data and workspace directories. Release `logs` and `backups` are local
directory junctions to the existing runtime directories, so desktop clients and
the service use the same token file and backup inventory.

Before activation, SQLite's backup API creates a consistent backup and checks its
integrity. A copied database is migrated first, with all pre-existing table row
counts preserved. After startup, production data tables are compared with the
backup and served assets are compared with the installed release files.

The local deployment evidence, machine configuration and rollback backups stay
outside Git. The desktop V2.4 shortcut starts the active release; the restart
launcher requests an authenticated shutdown and waits for it before starting.
No credentials, databases or personal deployment artifacts belong in this repo.
