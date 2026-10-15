# Handoff <timestamp>_<agent>_<unique-id>

- Project: <slug>
- Agent: <agent>
- Timestamp (UTC): <timestamp>
- Status: VERIFIED | REPORTED_UNVERIFIED | PROPOSED | BLOCKED
- Risk level: ROUTINE | MEDIUM | HIGH
- Review state: REVIEW_OPTIONAL | REVIEW_REQUIRED | REVIEW_BLOCKED | REVIEWED
- Context revision pinned: <context-repo commit SHA actually read>

## Task
What were you authorized to do?

## Actions / results
What actually changed? Keep fact and interpretation distinct.

## Evidence
Concrete commit, command/test output, or artifact; use NOT_VERIFIED if none.

For an implementation record, state the **tested source commit SHA** and paste the **actual
command output** — not a summary, and not "should pass".

| Item | Value |
| --- | --- |
| Tested source SHA | |
| Test command | |
| Actual result | |
| CI status | `PASS` / `FAIL` / `NOT VERIFIED (no CI configured)` |
| Known failing baseline (with test IDs) | |
| Failure set this run (with test IDs) | |
| Regressions vs baseline | none / list — or "not computable: baseline has no test IDs" |

## Review
- Who reviewed (if anyone), and at exactly which revision.
- If the task is HIGH risk and no review happened: record `REVIEW_BLOCKED` and say why.
  **A blocked release is a correct outcome. Do not skip the check because a reviewer had no quota.**

## Risks / uncertainty
Potential failures and untested assumptions.

## Next step
What should the next agent or user do?
