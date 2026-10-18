# Snapshot provenance

Prepared on 2026-10-18 as a clean source snapshot for private Grok review.

- Base application and committed integration features: local branch `v23-integration` at `abd48ea47e8880cf93280f7745153526f6cb485d`.
- Current DNS-pinning connector implementation and three focused regression tests: copied from the working tree `v23-deepseek-connectors`; they were not committed in that worktree when this snapshot was prepared.
- Studio `os` import fix: copied from the working tree `v23-origine`; it was not committed there when this snapshot was prepared.
- Parent-process selection correction in the sandbox test: taken from `v23-codex-security` commit `36b7b39d5235230e07fded7a514313b30203f148`.

This repository starts with one new snapshot commit rather than the local project's full Git history. Local databases, logs, backups, personal handoff conversations, and credential values were excluded. The snapshot is for review and collaboration, not deployment; verify all behavior against the code and tests.
