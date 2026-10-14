# AI Context Hub

**Project context that travels across AI tools — without a new agent server.**

*跨 AI 的项目上下文共享与可验证交接，而不是另一个聊天机器人。*

**v0.1.0 · Git + Markdown · On-demand · Python 3.10+ · No model API required**

[中文：项目背景、痛点与价值](docs/WHY_IT_EXISTS_ZH.md) · [中文部署指南](docs/DEPLOYMENT_ZH.md) · [Architecture](docs/ARCHITECTURE.md) · [Security](docs/SECURITY.md)

## Why this project exists

Working with multiple AI tools introduces a coordination problem: **the work may move between tools, but project context and evidence do not reliably move with it.** Chat sharing links are not general-purpose conversation APIs, and manually pasting long chats leads to stale context, repeated explanations, lost decisions, and unverifiable claims of completion.

AI Context Hub solves a narrower, practical problem: **on request, each authorized agent can read the same project record and publish an attributable handoff that another agent can inspect and verify.**

| Pain point | What the hub provides |
| --- | --- |
| Conversations are isolated across AI apps | Shared, tool-neutral Markdown project context |
| Re-explaining background at every handoff | On-demand access to goals, constraints, decisions, current status, and recent handoffs |
| "Agent A says it is done" is not evidence | Named handoffs with evidence fields, timestamps and Git commit history |
| Agent updates can collide or be lost | Unique append-only handoff files, guarded Git sync and explicit conflict handling |
| A full agent orchestration platform is overkill | CLI built with the Python standard library + Git; no server, database or extra model API |

### Example: a multi-agent software project

1. A human and a planning AI agree on the scope and record the approved decisions.
2. An implementation agent reads the latest context, makes changes **in the separate application repository**, then writes a factual handoff with test evidence.
3. A reviewer agent reads the same context and the previous handoff, checks the implementation independently and publishes a second review record.
4. The planning AI reads both records from the private context repository to continue the discussion without relying on copied chat history.

**The original application source and runtime tests remain the authority for whether a feature actually works.** This tool provides coordination and traceability, not proof-by-self-report.

### What it deliberately does not do

- No automatic capture or mirroring of complete ChatGPT, Codex, WorkBuddy, or other chat sessions.
- No live shared model memory, hidden-state access, autonomous task scheduling, or always-on agents.
- No guarantee that every AI tool has read/write access: credentials and permissions must be configured and verified per tool.
- No promise of lower token spend, faster delivery, or fewer bugs without measuring those outcomes in real workflows.
- No complete secret-scanning guarantee; humans must review what is uploaded to any remote, including a private one.

See the [Chinese project story and problem/solution guide](docs/WHY_IT_EXISTS_ZH.md) for the product rationale, practical workflow, system boundaries, and acceptance criteria.

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

v0.1.0 has been published as a standalone public tool. A private-repository handoff was exercised across separate WorkBuddy and Codex runs and independently read through ChatGPT's authorized GitHub connector; this validates the **on-demand record-sharing path** for that particular environment, not automatic cross-platform chat synchronization. GitHub Actions checks the maintained Python test matrix. Other installations still need their own credential, read/write, and readback verification. The public package contains no private project records.

License: **not yet chosen**; ask the repository owner before external redistribution or open-source licensing.
