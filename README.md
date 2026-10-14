# AI Context Hub

**v0.1.0 — Git-backed, on-demand project context sharing for multiple AI tools**

[中文使用指南](docs/DEPLOYMENT_ZH.md) · [Architecture](docs/ARCHITECTURE.md) · [Security](docs/SECURITY.md)

AI Context Hub lets different AI tools read the same project context and publish traceable handoffs **when instructed**. Its storage is ordinary UTF-8 Markdown in a private Git repository; GitHub is the recommended host, but any compatible Git remote works.

**It does NOT** automatically intercept ChatGPT/WorkBuddy/Codex conversations, stream their hidden states, run an agent server, or certify an implementation solely from another agent's report.

## Architecture

```text
You approve work and request a sync
          |
ChatGPT / WorkBuddy / Codex
          | (Git clone/pull/push or an authorized GitHub connector)
          v
PRIVATE Git repository: my-ai-context
    projects/<id>/PROJECT_CONTEXT.md
    projects/<id>/DECISIONS.md
    projects/<id>/CURRENT_STATUS.md
    projects/<id>/handoffs/<unique id>.md  (append-only)
          |
          v
Application/source-code repositories and their tests (separate)

PUBLIC Git repository: ai-context-hub (this implementation + safe examples only)
```

## Requirements

- Python 3.10+ and Git (no pip dependencies, server, database or model API)
- Access to a **private** Git repository for project records
- User-approved credentials on each participating machine/connector

## Quick start

First create a private, initialized repository in GitHub named e.g. `my-ai-context` (or use your own remote), then clone it locally. These commands run *inside your private clone*:

```bash
python /path/to/ai-context-hub/src/ach.py --root . init --project demo --name "Demo Project"
python /path/to/ai-context-hub/src/ach.py --root . validate --project demo
# First-time bootstrap files need review and an initial commit:
git add projects/demo && git commit -m "Initialize demo context" && git push
python /path/to/ai-context-hub/src/ach.py --root . read --project demo --sync
python /path/to/ai-context-hub/src/ach.py --root . handoff --project demo --agent workbuddy --task "Inspect" --result "Read files" --evidence "commit abc123" --status VERIFIED
python /path/to/ai-context-hub/src/ach.py --root . sync-push --project demo
```

The default `read` is local; `read --sync` first fetches and fast-forwards to the latest remote state. Never claim you read *current* shared context when your pull failed.

`sync-push` accepts **only newly created handoff Markdown files**. It refuses unrelated or tracked file changes. Decisions and status updates require separate, explicitly reviewed commits/PRs, avoiding agent overwrite of shared decisions. Concurrent independent handoffs are supported through unique filenames and guarded Git pushes. No forced pushes.

Configure a Git author name and email in each clone before publishing. `sync-push`
checks author/committer identity before staging. If signing or a commit hook fails,
it unstages only the attempted logs and leaves their files intact. If a push fails,
logs remain committed locally: fix the connection/permissions and rerun the same
command. It checks every unpublished commit and refuses unrelated changes,
existing-log edits, unsafe files and detected credentials before pushing.

Concurrent updates from separate clones append a merge commit without rewriting
either handoff commit. A filename collision stops for manual review, even when
the contents match. `sync-pull` and `sync-push` share a per-checkout lock;
use separate clones for separate agents and do not run external Git mutations
during a sync. After a process crash, inspect `.git/ach-sync.lock` and confirm no
sync is running before manually removing a stale lock. No automatic lock stealing.

## Commands

| Command | Effect |
| --- | --- |
| `init` | Create a project context with templates (local only) |
| `read [--sync] [--last N]` | Assemble verified-source context and latest handoffs |
| `handoff` | Create an independent timestamped report |
| `validate` | Check required files and obvious credential patterns |
| `sync-pull` | Fetch + fast-forward remote, refuse dirty tracked files |
| `sync-push` | Commit/push only new handoffs; guarded concurrent updates |

## Reliability contract

1. Separate `VERIFIED`, `REPORTED_UNVERIFIED`, `PROPOSED`, and `BLOCKED`.
2. A status statement requires concrete evidence: repository commit, command output or observable artifact.
3. Agents write **new** handoff files, never clobber another agent's log.
4. Major changes to shared decisions require user review.
5. Never store credentials, company confidential records, brokerage details or raw unapproved chat histories.
6. A new repository is **not** connected merely because it exists; test read/write access for each agent.

## Running tests

```bash
python -m unittest discover -s tests -v
```

Tests include a local bare Git remote with two independent agent clones and concurrent handoff generation.

## Release status

Local MVP and tests available. GitHub remote creation, authorized multi-tool read/write and real private-project end-to-end tests require separate verification. The public package contains no real private project records.

License: **not yet chosen**; ask the repository owner before external redistribution or open-source licensing.
