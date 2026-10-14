# AI Context Hub

**Project context, approved task packets and UAT feedback that travel across AI tools — without a new agent server.**

*跨 AI 的项目上下文共享、已批准任务包与 UAT 缺陷闭环，而不是另一个聊天机器人。*

**v0.3.0 · Git + Markdown · On-demand · Python 3.10+ · No model API required**

[中文：项目背景、痛点与价值](docs/WHY_IT_EXISTS_ZH.md) · [中文部署指南](docs/DEPLOYMENT_ZH.md) · [Architecture](docs/ARCHITECTURE.md) · [Task packets & UAT](docs/TASK_PACKET.md) · [Source onboarding](docs/SOURCE_ONBOARDING.md) · [Security](docs/SECURITY.md) · [3-agent pilot runbook](docs/PILOT_RUNBOOK.md)

## Why this project exists

Working with multiple AI tools introduces a coordination problem: **the work may move between tools, but project context and evidence do not reliably move with it.** Chat sharing links are not general-purpose conversation APIs, and manually pasting long chats leads to stale context, repeated explanations, lost decisions, and unverifiable claims of completion.

AI Context Hub solves a narrower, practical problem: **on request, each authorized agent can read the same project record and publish an attributable handoff that another agent can inspect and verify.**

| Pain point | What the hub provides |
| --- | --- |
| Conversations are isolated across AI apps | Shared, tool-neutral Markdown project context |
| Re-explaining background at every handoff | On-demand access to goals, constraints, decisions, current status, and recent handoffs |
| "Agent A says it is done" is not evidence | Named handoffs with evidence fields, timestamps and Git commit history |
| Agent updates can collide or be lost | Unique append-only handoff files, guarded Git sync and explicit conflict handling |
| An approved plan quietly drifts while it is being built | An approved packet binds its brief, acceptance criteria and asset manifest; a post-approval edit cannot be published |
| A defect report arrives as another ZIP of the source tree | UAT records reference the tested commit and PR, and are readable in place |
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
You approve the plan, then trigger a sync or publish
          |
ChatGPT / WorkBuddy / Codex
          | (Git clone/pull/push or an authorized GitHub connector)
          v
PRIVATE Git repository: my-ai-context
    projects/<id>/PROJECT_CONTEXT.md
    projects/<id>/DECISIONS.md
    projects/<id>/CURRENT_STATUS.md
    projects/<id>/handoffs/<unique id>.md  (append-only agent logs)
    projects/<id>/tasks/<task-id>/         (approved implementation packet)
        BRIEF.md  ACCEPTANCE.md  ASSETS.md
        APPROVAL.md                        binds the approved packet text to SHA-256 hashes
        assets/<approved files>            hash-verified evidence images
    projects/<id>/uat/<feedback-id>/       (append-only UAT defect records)
        UAT_FEEDBACK.md  ASSETS.md  assets/<screenshots>
          |
          v
Application/source-code repositories: branches, PRs, tests, builds (separate)

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
the contents match. Sync/publish commands and the multi-file approval, asset-manifest
and UAT-status updates share a per-checkout lock;
use separate clones for separate agents and do not run external Git mutations
during a sync. After a process crash, inspect `.git/ach-sync.lock` and confirm no
sync is running before manually removing a stale lock. No automatic lock stealing.

### v0.2 workflow: packet → implementation → UAT

```bash
# Prove the access this workflow depends on before promising a review
python .../ach.py --root . onboard-check --source-repo git@github.com:you/demo-app.git --prove-push

# Draft, approve and publish an implementation packet
python .../ach.py --root . task-new --project demo --task task-1 --title "Fix checkout copy" \
    --accountable workbuddy --source-repo git@github.com:you/demo-app.git \
    --scope "Correct the checkout button label." --expected "Label is correct and tests pass."
python .../ach.py --root . task-asset  --project demo --task task-1 --file ./approved-mock.png \
    --origin "approved design mock" --approved-by <you>
python .../ach.py --root . task-approve --project demo --task task-1 --approved-by <you> \
    --statement "Approved: this revision is the one to build."
python .../ach.py --root . task-publish --project demo --task task-1

# An agent reads the packet, implements elsewhere, and records real evidence
python .../ach.py --root . task-read --project demo --task task-1 --sync
python .../ach.py --root . handoff --project demo --agent workbuddy --task "Implement task-1" \
    --result "Changed the checkout label" --evidence "commit <sha>" \
    --source-repo git@github.com:you/demo-app.git --branch fix/checkout-copy --code-sha <sha> \
    --pr https://github.com/you/demo-app/pull/12 --build "npm test" --tests "12 passed" \
    --acceptance PENDING --status VERIFIED

# The human tests the build and reports a defect without sending a ZIP
python .../ach.py --root . uat-new --project demo --task task-1 --reporter <you> \
    --source-repo git@github.com:you/demo-app.git --tested-commit <sha> \
    --environment "macOS 15 / build 2026-10-14" --steps "1. Open checkout  2. Click Pay" \
    --expected "Payment starts" --observed "Button does nothing" --severity high \
    --screenshot ./bug.png
python .../ach.py --root . uat-publish --project demo --feedback <id>
python .../ach.py --root . uat-status  --project demo --feedback <id> --status fixed \
    --by codex --related-pr https://github.com/you/demo-app/pull/13 --note "regression test added"
```

A published packet can never be overwritten: changing it requires a new task id or
revision. A published UAT record may only grow — appending a status line or a new
screenshot is allowed, rewriting or deleting published content fails closed.

Approval and UAT author names are recorded assertions. The CLI preserves and checks them,
but does not authenticate a human identity. Host access controls, protected branches and
human review provide that authority. Run `onboard-check --prove-push` for a current write
test; seeing an older commit on the remote proves read/history only.

The full manual 3-agent pilot (planning AI approves, implementation agent builds,
reviewer agent verifies, human runs UAT) is in the
[3-agent pilot runbook](docs/PILOT_RUNBOOK.md).

### v0.3 workflow: existing local project → separate private source repository

This is the step that removes the ZIP. Inspection is read-only; nothing is staged, committed
or pushed until you approve the exact file list.

```bash
# 1. Look before touching anything (read-only: writes nothing into the project)
python .../ach.py source-inspect --path "$HOME/Desktop/Some Project"

# 2. Create the destination PRIVATE repository, then plan the upload
mkdir -p ~/source-onboarding/some-project
python .../ach.py source-plan \
    --path "$HOME/Desktop/Some Project" --project some-project \
    --dest git@github.com:you/some-project.git \
    --workdir ~/source-onboarding/some-project \
    --mode snapshot --deny 'artifacts/*' \
    --authorize "<you>" --statement "Approved: first upload of the reviewed file list"
# -> prints the digest of the exact file list in SOURCE_MANIFEST.txt
#    --mode snapshot publishes ONE commit with only these files and never uploads the
#    project's own history; --mode history (default) publishes the existing commits

# 3. Read the manifest, then approve that digest
python .../ach.py source-publish --workdir ~/source-onboarding/some-project \
    --approve-manifest <digest>

# 4. Prove the upload with an independent fresh clone
python .../ach.py source-verify --workdir ~/source-onboarding/some-project

# 5. Record what each OTHER tool can actually do — never infer it
python .../ach.py source-access --workdir ~/source-onboarding/some-project \
    --tool chatgpt --status pending --evidence "connector not yet pointed at the repo"
```

Hard gates: denied file types (`.env`, keys, keystores, databases), credential patterns, and
denied paths **anywhere in the project's Git history** refuse the plan outright; archives,
backups and oversized files are excluded until explicitly promoted; a `github.com`
destination that is readable without authentication is refused as public; an existing
different `origin` is a hard refusal; divergence stops the upload instead of forcing; and the
pushed tree must equal the approved manifest byte for byte.

`source-verify` proves only that **this machine** can push and read back. Until a second tool
records a verified read with `source-access`, the summary reports
`VERDICT: sharing NOT VERIFIED`. See [Source onboarding](docs/SOURCE_ONBOARDING.md).

## Commands

| Command | Effect |
| --- | --- |
| `init` | Create a project context with templates (local only) |
| `read [--sync] [--last N]` | Assemble verified-source context, latest handoffs and a packet/UAT index |
| `handoff` | Create an independent timestamped report, optionally with implementation evidence |
| `validate` | Check required files, packet integrity, manifest hashes and credential patterns |
| `sync-pull` | Fetch + fast-forward remote, refuse dirty tracked files |
| `sync-push` | Commit/push only new handoffs; guarded concurrent updates |
| `onboard-check` | Verify context read, source-repo read and push permission; `BLOCKED` when unproven |
| `task-new` | Draft `tasks/<task-id>/` with brief, acceptance criteria and asset manifest |
| `task-approve` | Record the human approval bound to the brief's SHA-256 (runs once per task) |
| `task-asset` | Register one approved image with size, type, name and hash checks |
| `task-publish` | Publish an approved, verified packet; never force-pushes or overwrites |
| `task-read` | Read a packet and re-verify its approval binding and manifest hashes |
| `uat-new` | Record a standardized defect report with an optional screenshot |
| `uat-status` | Append a status transition (`reported`/`reproduced`/`fixed`/`re-tested`) |
| `uat-publish` | Publish a UAT record; published history is append-only |
| `uat-read` | List or read UAT feedback records with their current status |
| `source-inspect` | Read-only inspection of a local project before onboarding |
| `source-plan` | Plan a first upload: exact file list, destination check, owner authorization |
| `source-publish` | Non-destructive first upload (or later push) of the approved manifest |
| `source-verify` | Fresh-clone read-back proving the commit SHA and every file byte |
| `source-access` | Record one other tool's own read access to the source repository |

## Reliability contract

1. Separate `VERIFIED`, `REPORTED_UNVERIFIED`, `PROPOSED`, and `BLOCKED`; the same applies to the UAT statuses.
2. A status statement requires concrete evidence: repository commit, command output or observable artifact.
3. Agents write **new** handoff files, never clobber another agent's log.
4. Major changes to shared decisions require user review.
5. Publishing a task packet requires a prior human approval record; a brief edited after approval no longer binds and publication is refused.
6. AI implementation is not human acceptance. `--acceptance PASSED` is refused unless it references a `re-tested` UAT record.
7. Binary asset upload is only supported through the local CLI. A connector that cannot carry binaries must report that limitation instead of claiming success.
8. Never store credentials, company confidential records, brokerage details or raw unapproved chat histories.
9. A new repository is **not** connected merely because it exists; test read/write access for each agent.

## Running tests

```bash
python -m unittest discover -s tests -v
```

The suite builds real temporary bare Git remotes and covers:

- two independent agents publishing handoffs concurrently without overwriting either log;
- packet publication, read-back from a fresh clone, and idempotent repeated publication;
- rejected-and-resumed pushes, commit-hook failures, missing Git identity, missing remote and pre-existing local changes — all failing closed with the local bytes preserved;
- asset manifest/hash verification plus oversized, spoofed, wrongly-named and traversal-shaped asset rejection;
- append-only UAT history: status transitions survive, rewrites and deletions fail closed;
- acceptance gating, so an AI cannot declare human UAT passed without a `re-tested` record;
- an onboarding verdict that reports `BLOCKED` rather than assuming access;
- a guard asserting the public repository contains no real project, private repository or customer references.

All fixtures are synthetic: no real user, business project, chat transcript or private image is used.

## Release status

v0.1.0 published the context and handoff loop. A private-repository handoff was exercised across separate WorkBuddy and Codex runs and independently read through ChatGPT's authorized GitHub connector; this validates the **on-demand record-sharing path** for that particular environment, not automatic cross-platform chat synchronization.

v0.2.0 adds the approved task packet, the hash-verified asset handoff, evidence-based completion records, the UAT defect loop and the fail-closed onboarding check. The local test suite passes on the maintained Python versions (3.10, 3.11, 3.13), and the public package contains no private project records.

The v0.2 workflow has not yet been exercised end-to-end by a second tool on a real project. Each participating tool still needs its own credential, read/write and read-back verification, which `onboard-check` reports honestly instead of assuming.

v0.3.0 adds **application-source repository onboarding** for the gap recorded in issue #4:
read-only inspection of an existing local project, a manifest the owner approves by digest, a
non-destructive first upload into a separate private repository, an independent fresh-clone
read-back, and a per-tool access record that keeps "this machine can read it" separate from
"another AI tool can read it". Six of the seven acceptance gates from that issue are now
implemented and covered by tests; remote repository creation still requires the owner's
account authorization and is reported as a setup requirement rather than assumed.

License: **not yet chosen**; ask the repository owner before external redistribution or open-source licensing.
