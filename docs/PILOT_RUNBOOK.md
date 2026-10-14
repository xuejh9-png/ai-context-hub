# Manual 3-agent pilot runbook (v0.2)

Purpose: prove, on a **real but low-risk** project, that an approved packet can travel from
a planning AI to an implementation agent, that the implementation can come back as
evidence rather than a claim, and that a human defect report can reach the code without
anyone exchanging a ZIP of the source tree.

Use a throw-away or non-critical project for the first run. Do not pilot on anything you
cannot afford to have an agent read.

## Participants and what each one is for

| Role | Default tool | Responsibility in this pilot |
| --- | --- | --- |
| Planning AI | ChatGPT | prepares the packet, later reads the UAT record and the completion handoff |
| Implementation agent | WorkBuddy | reads the packet, implements in the source repository, pushes a PR, records evidence |
| Review agent | Codex | independently checks the code and evidence, adds a regression test, publishes the repair |
| Owner | you | approves the packet, tests the build, reports the defect, accepts the result |

## Prerequisites

1. A **private** context repository (`my-ai-context` or your own) cloned on the machine that
   runs the CLI. Never put pilot records in the public tool repository.
2. A **separate** application repository with a real commit SHA. The context repository must
   not contain application code.
3. Git author name/email configured in each clone — publication fails closed without them.
4. Credentials for each participating tool, obtained through that tool's own authorization.

## Step 0 — Prove the access before promising anything

```bash
python /path/to/ai-context-hub/src/ach.py --root . onboard-check \
    --source-repo <source repo URL> --prove-push
```

Gate: the verdict must be `READY`, with `CONTEXT_READ`, `SOURCE_READ` and `CONTEXT_PUSH`
all `PASS`. If the source remote is not readable, stop and arrange access — do **not** ask
the user for a ZIP of the project. `--prove-push` pushes a temporary `refs/ach-onboard/*`
ref, reads it back and deletes it, so it is a real write proof rather than an assumption.

Record the result in a handoff (`--agent <tool>`, `--status VERIFIED`) so the pilot has
evidence for the access claim.

## Step 1 — Planning AI prepares the packet

```bash
python .../ach.py --root . task-new --project <slug> --task pilot-1 \
    --title "Pilot: <the one change>" --accountable workbuddy --revision v1 \
    --source-repo <source repo URL> --baseline-sha <current source HEAD sha> \
    --scope "<what is in scope, precisely>" --out-of-scope "<what is not>" \
    --expected "<observable result>" --request "<why>"
python .../ach.py --root . task-asset --project <slug> --task pilot-1 \
    --file ./approved-mock.png --origin "<where this image came from>" --approved-by <you>
python .../ach.py --root . task-read --project <slug> --task pilot-1
```

Gate: `task-read` prints `PASS: manifest, approval binding and secrets all verified.` and
`Not approved. Publication is not allowed.` At this point nothing is on the remote yet.

## Step 2 — Owner approves, then the packet is published

```bash
python .../ach.py --root . task-approve --project <slug> --task pilot-1 --approved-by <you> \
    --statement "Approved: this revision is the one to build."
python .../ach.py --root . task-publish --project <slug> --task pilot-1
```

Gate: `task-publish` prints `PUSHED: <sha>`, and a fresh clone can read
`projects/<slug>/tasks/pilot-1/BRIEF.md` **and** `assets/<the image>` with matching hashes.
Verify from a second clone — that is the read-back half of the test.

Optional negative check: edit `ACCEPTANCE.md` and rerun `task-publish`. It must refuse with
`An approved task packet already exists on origin/... with different content`, leaving the
remote untouched. This is the "never overwrite an approved task" guarantee.

## Step 3 — Implementation agent works from the packet

```bash
git clone <context repo URL> context && cd context
python .../ach.py --root . task-read --project <slug> --task pilot-1 --sync
```

Gate: the agent can restate the approved scope and the out-of-scope list verbatim from the
packet as printed by `task-read`, not from chat memory. If the packet is missing, stale or
contradicts the brief it was given, it reports `BLOCKED` instead of implementing.

Then, in the **application repository** (a separate clone):

```bash
git checkout -b pilot/<task-id>
# ... make the change ...
python -m unittest discover -s tests -v      # or the project's real test command
git commit -am "<change>" && git push -u origin pilot/<task-id>
# open a PR; do not push to main
```

Then record the evidence in the context clone:

```bash
python .../ach.py --root . handoff --project <slug> --agent workbuddy \
    --task "Implement pilot-1" --result "<what actually changed>" --evidence "commit <sha>" \
    --source-repo <source repo URL> --branch pilot/pilot-1 --code-sha <full sha> \
    --pr <PR URL> --build "<build/run command>" --tests "<actual test output>" \
    --acceptance PENDING --status VERIFIED
python .../ach.py --root . sync-push --project <slug>
```

Gate: the handoff contains the real SHA and PR, the real test output, and
`Human acceptance: PENDING`. An implementation record without a real SHA, branch or PR is
refused — that is by design.

## Step 4 — Owner tests the build and reports a defect

Follow the PR's build instructions, then:

```bash
python .../ach.py --root . uat-new --project <slug> --task pilot-1 --reporter <you> \
    --source-repo <source repo URL> --tested-commit <the tested sha> \
    --environment "<OS / build / version>" --steps "1. ... 2. ... 3. ..." \
    --expected "<what should happen>" --observed "<what happened>" --severity high \
    --impact "<who is blocked>" --related-pr <PR URL> --screenshot ./defect.png
python .../ach.py --root . uat-publish --project <slug> --feedback <id>
```

Gate: a fresh clone can read the record, its tested commit matches the commit that was
actually built, and the screenshot hash matches its manifest entry.

## Step 5 — Review and fix loop

```bash
# Reviewer reproduces and fixes
python .../ach.py --root . uat-status --project <slug> --feedback <id> --status reproduced \
    --by codex --note "reproduced locally on <platform>"
# ... add a small regression test, open a repair PR ...
python .../ach.py --root . uat-status --project <slug> --feedback <id> --status fixed \
    --by codex --related-pr <repair PR URL> --note "regression test added"
python .../ach.py --root . uat-publish --project <slug> --feedback <id>
```

Gate: `uat-publish` succeeds by **appending**; the original report text is still present in
the remote copy. Try rewriting an earlier line and confirm the publish is refused.

## Step 6 — Owner retests and acceptance is recorded

```bash
python .../ach.py --root . uat-status --project <slug> --feedback <id> --status re-tested \
    --by <you> --note "retest passed on <build>"
python .../ach.py --root . uat-publish --project <slug> --feedback <id>

python .../ach.py --root . handoff --project <slug> --agent workbuddy \
    --task "Close pilot-1" --result "Defect fixed and retested" --evidence "PR <url>" \
    --source-repo <source repo URL> --branch pilot/pilot-1 --code-sha <sha> --pr <PR URL> \
    --build "<build command>" --tests "<test output>" --acceptance PASSED --uat <feedback id> \
    --status VERIFIED
```

Gate: `--acceptance PASSED` is only accepted because a `re-tested` record exists. Try the
same handoff before the retest status and confirm it is refused.

## Pilot exit criteria

- [ ] `onboard-check` returned `READY`, and the result is recorded with evidence.
- [ ] A fresh clone can read the packet's `BRIEF.md`, `ACCEPTANCE.md`, `ASSETS.md`, `APPROVAL.md` and the approved image with matching hashes.
- [ ] The implementation handoff contains a real commit SHA, PR, build/run instructions and actual test output, and states `Human acceptance: PENDING`.
- [ ] The UAT record references the commit that was actually tested and carries reproducible steps, expected vs observed, severity and a screenshot hash.
- [ ] The defect was fixed through a PR with a regression test, and the record shows the full `reported → reproduced → fixed → re-tested` history.
- [ ] Rewriting or deleting published packet/UAT content was refused, with local bytes preserved.
- [ ] No private project data, credential or raw chat transcript reached the public repository.
- [ ] Each tool's read **and** write access was observed separately.

## Known limits of this pilot

* It does not prove automatic cross-tool chat synchronization; it proves an authorized
  session can read and write a shared record on request.
* A connector that cannot upload binaries cannot attach screenshots — use the local CLI.
* Code alone does not reveal current desktop state: for UI or runtime defects, the
  screenshot and operator-collected logs remain necessary inputs.
* No efficiency, token or defect-rate improvement has been measured yet; do not claim one
  until a baseline exists.
