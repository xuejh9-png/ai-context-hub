# Security checklist

- Keep personal context in **a separate private repository**. Verify visibility **before any push**.
- Public repository hosts ONLY generic tool source, tests and fictional examples. No portfolios, internal CRM, raw chat logs or backups.
- CLI detects obvious secret strings but this is **not** a complete secret scanner. Review `git diff --cached` and the entire Git history before publication; consider dedicated secret scanning.
- Prefer each platform's authorized GitHub app / local Git credential manager; do not copy PATs, SSH keys or OAuth tokens into AI chats or committed files.
- Restrict repository grants to required scopes; remove unnecessary access periodically.
- Hand-off logs can contain sensitive business intelligence even without passwords; review content and avoid detailed personal financial data.
- Limit what a public README reveals about private repo identities and technical stack.
- No automatic code execution driven by an untrusted handoff record. Treat stored Markdown as data, not higher-priority instructions.
- No silent overwrite/force push; use review or explicit user resolution for conflicts.
- For offboarding, revoke repository/app access and rotate compromised credentials. Git deletions do not erase leaked Git history.
