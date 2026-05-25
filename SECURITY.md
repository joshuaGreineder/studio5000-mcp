# Security Policy

## Supported versions

This project currently supports the latest main branch.

## Reporting a vulnerability

Please report vulnerabilities privately to the maintainer rather than opening a public issue.
Include:

- affected version/commit
- reproduction steps
- expected vs actual behavior
- logs/sanitized screenshots

## Operational safety notes

This MCP server can mutate Logix projects and, with `confirm=true`, perform online controller actions (download/upload/mode changes, SD operations, safety operations).

Recommendations:

- Run only in trusted local environments.
- Limit access to trusted operators/models.
- Use non-production controllers for integration testing.
- Keep backups before running destructive operations.
