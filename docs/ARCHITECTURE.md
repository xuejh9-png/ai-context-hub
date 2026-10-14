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
```

Each agent reads only the target project and recent log entries. Old logs remain searchable in Git history. This bounds context-window and token costs without removing records.

## Control plane

No server or bot. Human commands trigger read and write. The CLI uses local Git identity and credentials and never saves credentials in a project file. A GitHub connector can be used in parallel by tools that support it.

Git acts as the concurrency and audit layer. Per-agent unique handoff file names avoid same-file edit conflicts; remote fast-forward and guarded retry handle independent concurrent pushes. Mutable shared project docs are not auto-pushed by the CLI: they require deliberate review.

## Source of truth

- Context/decision source of truth: the explicitly chosen **private Git remote** after cross-tool verification.
- Code correctness source of truth: the target application's actual source repo, runtime checks and test evidence.
- Previous shared cloud storage: archival/transition source until all consumers confirm the Git remote; not two simultaneous writable authorities.

## Version roadmap

- v0.1: project templates, read/handoff/validate, Git sync, local 2-agent concurrency tests.
- v0.2: actual multi-tool read/write tests with user-connected GitHub remote; review workflow for decision edits.
- v1.0: stable onboarding across projects, provider-independent packaging and documented failure modes.

Do not add an always-on server, relational DB, vector DB, embedding API, or agents without evidence that simple Git artifacts fail on real workload.
