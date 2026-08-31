# Security and privacy

## Repository visibility

This project should be created as a **private GitHub repository** unless the owner explicitly approves a public release after a separate security review.

## Files that must never be committed

- `.env` and real API keys or access tokens.
- `data/` runtime files, including reports, realtime pools, read history, logs and task status.
- Android signing keys, keystores and generated APK/AAB packages.
- Local IDE settings, temporary files and machine-specific diagnostics.

The root `.gitignore` enforces these exclusions. API credentials are read from Windows environment variables and must never be copied into source code, documentation or GitHub settings as plain text.

## Before every push

1. Run `git status --short --ignored` and review every tracked file.
2. Scan tracked text for API keys, GitHub tokens and private-key headers.
3. Confirm the GitHub repository visibility is `PRIVATE`.
4. If a credential is ever committed, revoke it immediately and remove it from Git history before pushing again.

## Network exposure

The Flask development server is intended for local or trusted LAN use. Do not expose port 8899 directly to the public internet without authentication, TLS and a production server.
