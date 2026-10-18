# Security status and review boundaries

This is a development snapshot. It is not a security certification and must not be treated as permission to enable sensitive execution.

- MCP tool execution remains locked pending human review and OS-level validation.
- WSL alone is not a sandbox. The Linux path depends on kernel namespaces, restricted mounts, seccomp, and resource limits being applied and tested.
- The Windows-native sandbox backend is not approved for untrusted code.
- Never use a production database, API key, credential store, or live server for review or tests.
- The repository excludes local database files and credentials. Keep all future local state out of Git; see `.gitignore`.
- Treat behavior not demonstrated by a test or an observed runtime as unverified. Do not infer that a UI control works from its label alone.

Reviewers may identify security-relevant UX risks, such as unclear permissions or destructive actions, but must not unlock MCP, run commands, or propose bypassing authorization as a design improvement.
