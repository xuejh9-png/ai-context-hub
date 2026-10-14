# Release and integration acceptance checklist

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
