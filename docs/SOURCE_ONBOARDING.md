# Application-source repository onboarding (v0.3)

This closes the v0.2 gap recorded in
[issue #4](../../issues/4): v0.2 could *check access to* a source repository and publish
approved images, but it could not safely take an **existing local project** and put its code
into a **separate private repository**. Without that, a planning AI still had to be fed a ZIP
of the source tree.

## Three layers, kept apart

| Layer | Repository | Holds | Never holds |
| --- | --- | --- | --- |
| Tool | public `ai-context-hub` | CLI, docs, tests, synthetic examples | any real project |
| Context | private `my-ai-context` | briefs, decisions, handoffs, packets, UAT records | application code |
| Source | one private repo **per application** | that application's code and its GitHub issues/PRs | tool code, context records |

Source onboarding moves data from a local directory into the **source** layer only. It never
writes to the public tool repository and never writes application code into the context
repository.

## Commands

| Command | What it does | Writes to |
| --- | --- | --- |
| `source-inspect --path DIR` | Read-only inspection: Git facts, candidate upload set, hard denials, review items, ignored build directories | stdout (and `--out` if given) |
| `source-plan` | Computes the exact file list, checks the destination, records the owner's authorization, writes `SOURCE_PLAN.md` + `SOURCE_MANIFEST.txt` | the work directory only |
| `source-publish` | First upload (or a later push) of exactly the approved manifest; idempotent; serialized per local project; never force-pushes | history mode: project commit; snapshot mode: Git objects only; plus the destination repository and work-directory evidence |
| `source-verify` | Fresh clone into a temporary directory, verifies the commit SHA and every file byte for byte, then deletes the clone | the work directory only |
| `source-access` | Records one **other** tool's own read access, per tool | the work directory only |

`source-plan`, `source-publish`, `source-verify` and `source-access` share one work directory
that **must exist and must be outside the inspected project**, so inspection and planning can
never write into the project.

## Publishing modes

`source-plan --mode` chooses what the destination actually receives. The plan records the
mode, and `source-publish` honours the recorded value, so the mode cannot be changed after
approval.

| Mode | What the destination receives | When to use it |
| --- | --- | --- |
| `history` (default) | The project's existing commits, pushed as-is | You want the destination to be a real clone of the project, with its Git history |
| `snapshot` | One commit containing exactly the approved files. The project's branches, index, reflog, working tree and history are **not** modified and **not** uploaded | You want another tool to read the current code without publishing everything the project's history has ever contained |

`snapshot` is the honest answer to "please exclude this, but it is already committed". It is
built through a private index file and `git commit-tree`. The destination's verified snapshot
tip is passed directly as the next parent, so local branches, refs, reflogs, the index and the
working tree do not change. Snapshot commits carry an AI Context Hub lineage marker; an existing
branch without that marker is treated as unrelated history and refused. A failed push writes
`SOURCE_PENDING.md` in the work directory, and a retry reuses that exact commit. The pending file
is removed only after `SOURCE_RESULT.md` records success.

Both modes share every other gate: destination verification, digest approval, manifest
re-verification, the tree-equals-manifest check, divergence refusal and failure recovery.

A tracked path is necessarily in a project's history, so `--deny` combines with the mode:
under `history` a denied-but-committed path refuses the plan; under `snapshot` it is simply
absent from the destination, because no history is uploaded.

## The gates

1. **Read-only first.** `source-inspect` never stages, commits, moves or deletes anything. It
   reports the project's Git state, whether a remote exists, the candidate file set, and what
   it found that must not be uploaded.
2. **Hard denials are refusals, not exclusions.** Environment files, key material,
   keystores, databases and credential patterns abort planning. They cannot be overridden.
3. **History is checked too.** History mode scans historical path names and the bytes of reachable
   historical blobs. Credential patterns, denied types, archives/backups/dumps, oversized blobs,
   an incomplete scan, or owner-denied paths refuse the plan because pushing history would publish
   them. The tool never rewrites history; snapshot mode remains available.
4. **Archive/backup/oversized files need explicit promotion.** They are excluded by default
   and listed; `--allow-review` promotes them after a deliberate decision.
5. **The project's own `.gitignore` is respected.** For a Git project the selection is the
   already-tracked set, so a reviewed ignore file is what defines "source". Untracked files
   are listed as *not included*, never silently dropped.
6. **Private visibility must be verified, not asserted.** For a `github.com` destination the
   unauthenticated API must return exactly `404`, and authenticated Git access must succeed.
   `200` is public; API errors, rate limits and every ambiguous response fail closed. Publication
   repeats the privacy/access check after approval and again immediately before the push.
7. **Explicit owner authorization.** Planning requires `--authorize` (who) and `--statement`
   (what they decided), and publication requires `--approve-manifest <digest>`. That SHA-256
   binds the local project path, destination, branch, mode, planned HEAD, authorizer, statement
   and exact file manifest. Editing any publication-critical field invalidates the approval.
8. **The pushed tree must equal the approved manifest.** Before pushing, the tool compares both
   the path set and every immutable commit-blob byte against the approved size and SHA-256. This
   closes the gap where a working file changes after validation but before `git add`.
9. **Non-destructive Git handling.** An existing repository keeps its history and its
   `origin`; a different `origin` is a hard refusal (no repointing). A project without Git is
   initialised only after approval, and only with `git init`. There is no force-push, ever.
10. **Failures preserve everything.** A rejected or failed push leaves the local commit and every
    working file available and prints how to retry. Both modes bind a preserved retry commit in
    `SOURCE_PENDING.md`; history-mode commit failures restore the exact pre-command index bytes.
    Existing staged changes are refused up front rather than replaced.
11. **Divergence stops the upload.** If the destination already holds commits that are not
    ancestors of the local HEAD, the upload is refused instead of merging or forcing.
12. **The owner can declare their own deny patterns** with `--deny <glob>`. Those paths are
    excluded from the manifest, and if any of them appears in the project's Git history the
    plan is refused — because excluding a path locally does not remove it from history, and
    this tool never rewrites history. For a Git project that means `--deny` can only act on
    files that are not tracked yet (untracked additions, or a project without Git). Declaring
    a tracked path as denied is a request to be told the truth, not a way to hide it.
13. **Concurrent publication is serialized.** A host-local lock derived from the resolved project
    path prevents two work directories from committing or pushing that project at once. The lock is
    removed on normal success or failure; after a process crash, its reported lock file must be
    inspected and removed manually.
14. **History cannot change after approval.** History mode records the planned HEAD and requires the
    same branch and HEAD at publication. The only allowed successor is the exact one-commit retry
    already recorded by this tool after a failed push; its parent must be the approved HEAD.

## Honest limits

* **Remote repository creation is out of scope.** Creating a new private repository needs
  account-level authorization this tool does not hold. When the destination does not exist,
  it reports the exact setup requirement instead of inventing success.
* **`source-verify` proves only that this machine can push and read back.** Another AI
  tool's access is recorded per tool with `source-access` and is never inferred. Until a
  second tool records a verified read, the summary says
  `VERDICT: sharing NOT VERIFIED`.
* **Chat-connector binary upload is still unsupported.** Screenshots for UAT flow through the
  local CLI.
* **This is human-triggered.** No background syncing, no watching, no scheduled pushes.
* **Denied-pattern detection is not a complete secret scanner.** It is a strong default, not
  a substitute for reviewing the manifest.

## End-to-end flow

```bash
# 0. Look before touching anything
ach source-inspect --path "$HOME/Desktop/Some Project"

# 1. Create the destination PRIVATE repository in the browser, then plan
mkdir -p ~/source-onboarding/some-project
ach source-plan \
    --path "$HOME/Desktop/Some Project" \
    --project some-project \
    --dest git@github.com:<you>/some-project.git \
    --workdir ~/source-onboarding/some-project \
    --authorize "<you>" --statement "Approved: first upload of the reviewed file list"

# 2. Read SOURCE_MANIFEST.txt, then approve that exact digest
ach source-publish --workdir ~/source-onboarding/some-project \
    --approve-manifest <digest-printed-by-source-plan>

# 3. Prove the upload independently
ach source-verify --workdir ~/source-onboarding/some-project

# 4. Record what each OTHER tool can actually do (do not infer it)
ach source-access --workdir ~/source-onboarding/some-project \
    --tool chatgpt --status pending --evidence "connector not yet pointed at the repo"
ach source-access --workdir ~/source-onboarding/some-project \
    --tool codex --status verified --sha <exact-published-commit> \
    --evidence "cloned <url> and read src/main.py"
```

Then continue development normally in the source repository with branches and pull requests,
and record the resulting commit, PR, tests and acceptance state in a context handoff:

```bash
ach --root <context-clone> handoff --project <slug> --agent workbuddy \
    --task "Implement <task-id>" --result "<what changed>" --evidence "commit <sha>" \
    --source-repo <source repo URL> --branch <branch> --code-sha <sha> --pr <PR URL> \
    --build "<build command>" --tests "<actual test output>" --acceptance PENDING \
    --status VERIFIED
ach --root <context-clone> sync-push --project <slug>
```

The user-facing outcome: the owner reports a bug in a chat, the planning AI reads the exact
source commit through its connector, and nobody sends a ZIP again.
