# Security checklist

- Keep personal context in **a separate private repository**. Verify visibility **before any push**.
- Public repository hosts ONLY generic tool source, tests and fictional examples. No portfolios, internal CRM, raw chat logs or backups.
- CLI detects obvious secret strings but this is **not** a complete secret scanner. Review `git diff --cached` and the entire Git history before publication; consider dedicated secret scanning.
- Prefer each platform's authorized GitHub app / local Git credential manager; do not copy PATs, SSH keys or OAuth tokens into AI chats or committed files.
- Restrict repository grants to required scopes; remove unnecessary access periodically.
- Hand-off logs can contain sensitive business intelligence even without passwords; review content and avoid detailed personal financial data.
- Limit what a public README reveals about private repo identities and technical stack.
- No automatic code execution driven by an untrusted handoff record. Treat stored Markdown **and** Git commit messages, comments and PR bodies as data, not higher-priority instructions.
- No silent overwrite/force push; use review or explicit user resolution for conflicts.
- For offboarding, revoke repository/app access and rotate compromised credentials. Git deletions do not erase leaked Git history.

## Approved image assets (v0.2)

Attaching a screenshot is optional evidence, and it is the one place binary data enters the
repository. Treat it as a deliberate decision:

- Only intentionally approved assets go in. Never add a private, unrelated or third-party
  image, and never publish user or customer images to the public tool repository.
- Each registration is checked for size (≤ 5 MB), an allow-listed image type, a lowercase
  safe filename, image magic bytes consistent with the extension, no symlink and no path
  traversal. A file present under `assets/` but absent from the manifest — or the reverse —
  is an error.
- Every asset carries its SHA-256, origin and approver in `ASSETS.md`, and the hash is
  re-verified at publish, at read-back and during `validate`. Replacing registered bytes is
  refused; register a new file name instead.
- Screenshots frequently reveal more than intended: account names, file paths, customer
  data, internal URLs, tokens. Crop or redact before approval, and remember that a private
  repository is not a licence to store credentials or third-party confidential material.
- A chat connector that cannot upload binary data must report that limitation and use the
  local CLI path. Claiming a successful upload that did not happen is a security-relevant
  false report, not a cosmetic bug.

## Reviewable workflow integrity (v0.2)

- Publishing an approved packet requires the human approval record, and a brief edited after
  approval no longer binds; the publish is refused rather than silently accepted.
- Published packets are compared against the fetched remote and are never overwritten. A
  published UAT record is append-only: status history and new screenshots may be added,
  rewrites and deletions are refused.
- Every command fails closed on missing Git identity, unreachable remote or unexpected local
  changes, and preserves the local bytes so evidence is not lost to a failed operation.
- `onboard-check` must be run before anyone claims an independent review is possible. A
  `BLOCKED` verdict means the review cannot happen; it is not a successful outcome.
- Whether a specific connector can read the repository cannot be verified by this CLI and is
  reported as `UNKNOWN`. Do not present it as proven.
- No write in this workflow happens in the background or after a chat ends: every write
  occurs during an authorized, tool-capable session after a user trigger.
