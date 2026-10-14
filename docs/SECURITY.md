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
  safe filename, basic container structure consistent with the extension, no symlink and no path
  traversal. A file present under `assets/` but absent from the manifest — or the reverse —
  is an error.
- Every asset carries its SHA-256, origin and approver in `ASSETS.md`, and the hash is
  re-verified at publish, at read-back and during `validate`. Replacing registered bytes is
  refused; register a new file name instead.
- Screenshots frequently reveal more than intended: account names, file paths, customer
  data, internal URLs, tokens. Crop or redact before approval, and remember that a private
  repository is not a licence to store credentials or third-party confidential material.
- Structural checks cannot detect sensitive pixels, steganography or all decoder bugs.
  Hashes prove byte identity after a human chose the image; they do not prove the image was
  safe or that the named approver's identity was authenticated.
- A chat connector that cannot upload binary data must report that limitation and use the
  local CLI path. Claiming a successful upload that did not happen is a security-relevant
  false report, not a cosmetic bug.

## Reviewable workflow integrity (v0.2)

- Publishing an approved packet requires the human approval record, and a brief edited after
  approval no longer binds; acceptance criteria and the asset manifest are bound too.
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
- Names in approval/UAT fields are assertions. Enforce identity and append-only Git history
  through repository permissions, protected branches and review; the CLI cannot prevent an
  authorized administrator from rewriting the remote.

## Onboarding application source (v0.3)

Moving an existing local project to a private repository is the highest-risk operation this
tool performs, because it can publish years of accumulated secrets in one push.

- **Inspect before you touch.** `source-inspect` is read-only by design and must be run first.
  It reports the candidate set, not a verdict to trust blindly.
- **Denials are refusals.** Environment files, private keys, keystores, databases, credential
  patterns inside file contents, and any denied path present in the project's Git **history**
  abort planning. They cannot be overridden by a flag, because pushing history publishes what
  the working tree no longer contains.
- **Archives, dumps, backups and oversized files** are excluded by default and need an explicit
  `--allow-review` decision. A backup that was never meant to leave the machine is a common
  leak, and `.gitignore` does not remove what history already has.
- **Visibility is verified, not asserted.** An unauthenticated API `200` proves the repository
  is public and refuses the upload. A repository that is not publicly readable but is
  reachable by Git on this machine is treated as private.
- **The approved digest is the authorization.** `source-plan` prints a SHA-256 over the exact
  file list; `source-publish` refuses without it and refuses again if any file changed since
  planning. The pushed tree is compared against the manifest in both directions.
- **Non-destructive Git only.** An existing `origin` that differs from the plan is a hard
  refusal; there is no repointing, no `git init` over an existing repository, no force-push and
  no automatic merge of divergent histories.
- **Failed operations leak nothing and lose nothing.** Every refusal happens before staging or
  pushing, and the local commit and files survive so the operator can retry the same command.
- **Never confuse "we can read it" with "they can read it".** The pushing machine's read-back
  says nothing about another tool's permissions. Record third-party access per tool; a public
  claim of a shared project requires both.
- **The host is the real boundary.** Repository visibility, branch protection and collaborator
  scopes are configured outside this tool; the CLI can only refuse to make things worse.
