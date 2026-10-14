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
