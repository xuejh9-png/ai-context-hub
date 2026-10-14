# Architecture and design boundaries

## Problem

Chat links are not generally machine-readable session APIs. Cross-platform access requires a shared, explicit data artifact. AI Context Hub provides an on-demand **project record**, not a hidden memory link or automatic conversation mirroring.

## Data plane

A Git repository of plain Markdown:

```text
my-ai-context/                     # PRIVATE, not bundled in this public repo
  projects/
    <project-id>/
      PROJECT_CONTEXT.md            # Goal, system, constraints
      DECISIONS.md                  # Explicit approved decisions and supersessions
      CURRENT_STATUS.md             # Observed, unverified, blocked
      handoffs/
        20261013T123456Z_codex_<unique>.md  # Agent-specific immutable log
      tasks/<task-id>/              # v0.2 approved implementation packet
        BRIEF.md                    # Scope, target repo, baseline, approval state
        ACCEPTANCE.md               # Verifiable acceptance criteria
        ASSETS.md                   # SHA-256 manifest of approved images
        APPROVAL.md                 # Approval assertion bound to packet-text hashes
        assets/<name>               # Approved evidence images
      uat/<feedback-id>/            # v0.2 append-only defect records
        UAT_FEEDBACK.md             # Tested commit, steps, expected vs observed, status history
        ASSETS.md, assets/<name>    # Reporter screenshots, hash-verified
```

Each agent reads only the target project, recent log entries and the packet it was asked to
build. Old logs remain searchable in Git history. This bounds context-window and token costs
without removing records.

Asset bytes are the only binary payload, and they are deliberately constrained: an allow-list
of image types, a 5 MB cap, a lowercase safe filename, image magic-byte validation, no
symlinks and no path traversal. Everything else the workflow stores is UTF-8 Markdown so it
stays diffable, reviewable and greppable.

## Control plane

No server or bot. Human commands trigger read and write. The CLI uses local Git identity and
credentials and never saves credentials in a project file. A GitHub connector can be used in
parallel by tools that support it.

Git acts as the concurrency and audit layer. Per-agent unique handoff file names avoid
same-file edit conflicts; remote fast-forward and guarded retry handle independent concurrent
pushes. Mutable shared project docs are not auto-pushed by the CLI: they require deliberate
review.

v0.2 keeps that model and adds explicit publication gates rather than a new control plane:

* `sync-push` remains restricted to **new handoff files**. Packet and UAT publication use
  separate commands with their own allowed-path predicates, so no existing rule is bypassed.
* Before any packet publish, the CLI verifies the approval record, re-hashes `BRIEF.md`, and
  re-verifies every registered asset against its manifest.
* Unpublished local commits are inspected file by file, not just the final diff, so an
  intermediate edit cannot hide behind a later "add only" state.
* Publication compares against the fetched remote: an identical packet is a no-op, a
  divergent one is refused. UAT records may only be appended to.
* Approval, asset-manifest and UAT-status writes use the same per-checkout lock as
  publication, preventing two local processes from silently losing one another's update.
* Git identity, remote reachability and permission are checked before staging, so a failure
  never leaves a half-staged index. No command force-pushes and none deletes published
  history.

An onboarding check exists because access is frequently assumed and rarely proven:
`onboard-check --prove-push` observes context read, source-repository read and current push permission, and
reports `BLOCKED` with the failing layer instead of letting an agent claim a review was
possible. Whether a specific chat connector can read the repository cannot be observed by
this CLI and is reported as `UNKNOWN`.

## Source of truth

- Context/decision source of truth: the explicitly chosen **private Git remote** after cross-tool verification.
- Code correctness source of truth: the target application's actual source repo, runtime checks and test evidence.
- Approved-packet source of truth: `BRIEF.md`, `ACCEPTANCE.md` and `ASSETS.md` together with
  their `APPROVAL.md` hash bindings; an implementation handoff does not redefine scope.

The approval and UAT actor names are recorded assertions rather than authenticated
identities. Git hosting permissions and review policy enforce who may publish. The CLI's
append-only checks operate on ordinary history; remote force-push protection is a hosting
configuration responsibility.
- Defect source of truth: the UAT record, which names the exact tested commit rather than an environment description.
- Previous shared cloud storage: archival/transition source until all consumers confirm the Git remote; not two simultaneous writable authorities.

## Verified deployment versus roadmap

- **v0.1 (shipped):** project templates, read/handoff/validate, Git sync, failure recovery and two-agent concurrency tests. In one authorized real-world pilot, WorkBuddy and Codex independently submitted private-repository handoffs; ChatGPT independently read back both records with a GitHub connector. This verifies an **on-demand artifact-sharing workflow**, not complete chat mirroring or universal read/write access across every platform.
- **v0.2 (shipped on a branch, pending review):** approved task packets with a hash-bound human approval, hash-verified image asset handoff, evidence-based completion records, the append-only UAT defect loop, and the fail-closed onboarding check. Covered by automated tests including concurrent handoff/packet publication and existing failure-recovery regressions.
- **v0.3 (this change):** application-source onboarding. A read-only inspection, a
  digest-approved file manifest, a non-destructive first upload into a **separate private
  source repository**, an independent fresh-clone read-back, and a per-tool access record. The
  three layers (public tool, private context, private source) are now explicitly isolated, and
  the CLI never writes application code into the context repository or tool code into a source
  repository. Remote repository creation is deliberately out of scope: it needs account-level
  authorization the tool does not hold, so it is reported as a setup requirement.

- **Next:** run the manual 3-agent pilot, exercise a real defect round trip, and measure actual time saved and failure rates against a baseline.
- **Longer term (only if justified):** provider-neutral packaging and better retrieval across growing project archives.

Do not add an always-on server, relational DB, vector DB, embedding API, or agents without evidence that simple Git artifacts fail on real workload.
