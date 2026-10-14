# Task packets, asset handoff and UAT records (v0.2)

This document is the schema and protocol reference for the v0.2 artifacts. It is the
authority an implementation agent should follow when it receives work.

## Why these artifacts exist

v0.1 answered "what is the project context and what did each agent do". v0.2 answers the
three questions that followed in practice:

1. **What exactly was approved?** A packet exists only after an approval record, and the
   approved brief is bound by hash, so the scope cannot silently drift while it is built.
2. **Which revision of the code is this about?** Completion records and defect reports
   carry the source repository, branch, exact commit SHA and PR.
3. **How does a defect come back without shipping the project again?** A standardized,
   append-only feedback record references the tested commit, and the next agent reads the
   exact code from the source repository instead of asking for another ZIP.

## On-disk schema

```text
projects/<slug>/
  PROJECT_CONTEXT.md            v0.1 — goal, architecture, constraints
  DECISIONS.md                  v0.1 — approved decisions, append-only
  CURRENT_STATUS.md             v0.1 — verified / unverified / blocked
  handoffs/<unique>.md          v0.1 — immutable per-agent logs
  tasks/<task-id>/              v0.2
    BRIEF.md                    approved scope, target repo and baseline
    ACCEPTANCE.md               verifiable acceptance criteria
    ASSETS.md                   asset manifest with SHA-256 per approved file
    APPROVAL.md                 human approval record bound to BRIEF.md's hash
    assets/<name>               approved evidence images (png/jpeg/gif/webp)
  uat/<feedback-id>/            v0.2
    UAT_FEEDBACK.md             append-only defect record with status history
    ASSETS.md                   manifest for attached screenshots (when present)
    assets/<name>               reporter screenshots
```

`<slug>` and `<task-id>` are lowercase letters, digits and hyphens (1–64 characters).
Asset names must be lowercase with a `png`/`jpeg`/`gif`/`webp` extension. Path traversal,
absolute paths and symlinks are rejected everywhere.

## Lifecycle and gates

```text
task-new  ────────► DRAFT        (local only; sync-push cannot carry it)
task-approve ─────► APPROVED     (once per task; binds BRIEF.md by SHA-256)
task-publish ─────► PUBLISHED    (immutable from then on)
uat-new ──────────► reported ──► reproduced ──► fixed ──► re-tested   (append-only)
handoff ──────────► AI DONE, human acceptance still PENDING
```

| Gate | Enforced by | Failure mode |
| --- | --- | --- |
| No packet without approved scope | `task-publish` requires `APPROVAL.md` and `- Approval: APPROVED` | `BLOCKED`, nothing pushed |
| Approved brief cannot drift | `APPROVAL.md` stores `BRIEF.md`'s SHA-256; re-checked at publish and at `task-read` | publication refused |
| Approval is a single decision | `task-approve` refuses when `APPROVAL.md` already exists | re-approval requires a new task id/revision |
| Approved assets are exactly the approved bytes | manifest SHA-256 vs file, image magic bytes, size ≤ 5 MB | publication refused |
| Only intended files are published | porcelain status must contain only that packet's allowed paths; every unpublished commit is inspected | unrelated/modified changes abort the publish |
| Evidence, not declarations | implementation handoffs require repo/branch/real SHA/PR/build/tests | handoff refused |
| AI done ≠ human accepted | `--acceptance PASSED` requires a referenced `re-tested` UAT record | handoff refused |
| History is not rewritten | published packets are compared against the remote; published UAT records must be a strict superset (append-only) | publish refused |
| Access is proven, not assumed | `onboard-check` verifies context read, source read and push permission | `BLOCKED` verdict |

## Asset rules

* Only intentionally approved images are attached. Never add a private, unrelated or
  third-party image to the packet or to a UAT record.
* A registration records `SHA-256`, `Bytes`, `Type`, `Origin`, `Approved by` and `Added (UTC)`.
  `--origin` and `--approved-by` are required; provenance is part of the evidence.
* Registration is idempotent for identical bytes and **refuses** to replace a registered
  asset with different bytes. Register the new file under a new name.
* A file present under `assets/` but absent from the manifest is an error, and vice versa.
* Binary assets are the only non-UTF-8 payload the CLI publishes; they are excluded from
  the text secret scan and instead validated by size, name and image magic bytes.

## User trigger protocol

Every write happens while an authorized session is running, after a user action. There is
no after-chat or background posting.

| Step | Who triggers | Command |
| --- | --- | --- |
| Prepare a packet | planning AI (with user input) | `task-new` |
| Approve the revision | **human only** | `task-approve` |
| Attach approved visuals | human / planning AI | `task-asset` |
| Publish the packet | planning AI or implementation agent | `task-publish` |
| Read and implement | implementation agent | `task-read`, then the source repo, then `handoff` + `sync-push` |
| Test the build | human | — |
| Report a defect | human (or an operator collecting logs) | `uat-new` (+ `--screenshot`) then `uat-publish` |
| Triage / fix / retest | implementation and review agents | `uat-status`, new PR, completion handoff |
| Verify access before promising a review | any agent | `onboard-check` |

## Connector limitations

* A chat connector that cannot upload binary data cannot attach a screenshot. Report that
  limitation truthfully and use the local CLI, which is the supported path for images.
* A connector's read permission does not imply write permission. Both must be observed
  separately and recorded in a handoff.
* `onboard-check` can prove context read, source read and push permission. Whether a
  specific connector can read the repository is verifiable only inside that connector and
  is reported as `UNKNOWN` by this CLI.

## Failure behaviour

All publishing commands are fail-closed:

* the local bytes and any local commits are preserved on every failure, so nothing has to
  be reconstructed from a chat transcript;
* the index is left clean when a commit fails, so the command can simply be rerun;
* no command ever force-pushes, rewrites remote history, or deletes a published record;
* a rejected push leaves the commit local and tells the operator to fix connectivity or
  permissions and rerun the same command.
