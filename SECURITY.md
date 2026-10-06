# Security

Please use GitHub private vulnerability reporting for this repository. Do not post credentials, personal course material, grades, or exploit details in public issues.

Personal mode must run only over stdio behind an appropriately scoped private tunnel. Never expose a personal-token MCP process through a public unauthenticated proxy.

Hosted mode is an experimental deployment candidate. Use one ASGI worker per SQLite database, an approved Canvas developer key, a configured OIDC provider, HTTPS, secret management, and the deployment checks in `docs/deployment.md`. Do not disable access-token audience checks, network destination validation, or browser CSRF protections.

The extraction subprocess is resource bounded, not a complete operating-system sandbox. Use a non-root isolated container and restrict filesystem/network access in production. Dependencies retain their own licenses.
