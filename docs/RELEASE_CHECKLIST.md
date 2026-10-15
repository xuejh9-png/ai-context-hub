# Release and integration acceptance checklist

## Public reuse gate — must pass before announcing an open-source release

- [x] Public repository exists (code is viewable).
- [ ] **License chosen and committed by the owner.** A public GitHub repository without a license is not legally equivalent to an open-source project. Do not announce it as MIT/Apache-licensed before the LICENSE file exists.
- [ ] A **clean unrelated machine/account** completes [中文五分钟上手](QUICKSTART_ZH.md) using its **own private** context repository, with no hard-coded user paths or project credentials.
- [ ] The tester independently confirms the second AI/tool's exact-commit read permissions, or explicitly records NOT VERIFIED if no such tool is available.
- [ ] GitHub Actions passes for Python **3.10, 3.11, 3.12 and 3.13** on the release commit; CLI `--help` and source compilation checks pass.
- [ ] Public default branch contains only synthetic sample projects; inspect changed files and **reachable history** for accidental confidential content.
- [ ] README, quickstart, security guidance, contributor guidance and issue template links work from the intended release commit.
- [ ] Owner decides whether a tagged release (e.g. `v0.3.0`) and GitHub Release notes are appropriate; a tag must point to the **actually verified** source commit, not an arbitrary branch tip.
- [ ] After these checks, label the release as **software that stores and transfers records on demand**, not auto-synced cross-platform AI memory.

## Adoption verification (first external user)

- [ ] The user can explain the three distinct locations: public tool, private context, optional private source.
- [ ] A new project can be created, read, and a handoff published without copying a full conversation.
- [ ] A second authorized tool can retrieve the same decision and handoff at a recorded SHA; private repository visibility remains private.
- [ ] The user can recover from an authentication failure or conflict **without** a force push.
- [ ] Feedback is collected about steps that are confusing, installation failures and unsupported environments. No unsupported productivity claims are made.


## Public code repository

- [ ] Separate GitHub repository created with **Public** visibility.
- [ ] Source contains only tool code, generic docs and fictional example data.
- [ ] Tests pass locally and in GitHub Actions.
- [ ] No committed secret, portfolio, business customer dataset, or real conversation archive.
- [ ] Owner decides on open-source license independently (none chosen by default).
- [ ] Public repository link opens without sign-in.

## Private context repository

- [ ] Separate GitHub repository created with **Private** visibility.
- [ ] Seed records are reviewed for sensitive information before first push.
- [ ] Agent A clones/reads, writes one unique handoff, pushes and reads it back.
- [ ] Agent B independently fetches Agent A handoff, writes another unique handoff, pushes and reads back.
- [ ] ChatGPT fetches both handoffs through its authorized connection and verifies the exact commit/state.
- [ ] Both agents fail closed when Git connection/authentication is unavailable.
- [ ] Old shared storage marked archive / read-only only **after** end-to-end acceptance.

## Product-level validation

- [ ] Share the public `README.md` without exposing private files.
- [ ] Onboard a second unrelated project using `init`, `read`, `handoff`, `sync-push`.
- [ ] Reproduce a status conflict and verify the agents request review instead of overwriting it.

## v0.2 task packet, asset handoff and UAT loop

- [ ] `onboard-check --source-repo <url> --prove-push` returns `READY` for every participating tool, and the result is recorded with evidence.
- [ ] A packet is created only after an explicit approved scope, and `task-publish` refuses while the brief is still `PENDING`.
- [ ] Repeated `task-publish` is a no-op; a post-approval brief edit is refused; an already-published packet with different content is refused rather than overwritten.
- [ ] A fresh authorized clone can read `BRIEF.md`, `ACCEPTANCE.md`, `ASSETS.md`, `APPROVAL.md`, the approved image, and the UAT record, with manifest hashes matching the bytes.
- [ ] Missing asset, missing permission, oversized/unsafe file, path traversal, failed fetch/push and pre-existing local changes all fail safely with local bytes preserved.
- [ ] `sync-push` still refuses packet and UAT files, so no existing rule was bypassed.
- [ ] A completion handoff carries a real source SHA, PR, build/run instructions, actual test evidence, and an honest `Human acceptance: PENDING` state.
- [ ] `--acceptance PASSED` is refused until a `re-tested` UAT record exists for the tested commit.
- [ ] Concurrent handoff and packet publication from two agents both survive, and the older failure-recovery tests remain green.
- [ ] Published UAT history is append-only: a status transition and a new screenshot publish, a rewrite or delete is refused.
- [ ] Public test fixtures contain no real user/business project, chat transcript or private image.
- [ ] CI is green on all supported Python versions, and the new tests actually ran (not skipped).
