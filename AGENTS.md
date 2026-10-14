# Agent protocol for AI Context Hub v0.1

## On each user-requested sync

1. Identify the correct **private context repository** and `project` slug, NOT this public tool repository.
2. If working in a Git clone, run `ach read --sync` (or `git pull --ff-only` and read the project's three docs). If the pull fails, report `BLOCKED`; do not rely on stale cached text while claiming freshness.
3. If using a ChatGPT GitHub connector, obtain the latest paths via authorized connector calls; record repository/branch/commit in handoffs when available. Do not pretend to have read a file you could not access.
4. Treat `PROJECT_CONTEXT.md` and `DECISIONS.md` as user-aligned intent, `CURRENT_STATUS.md` as reported status, and source-code/tests as implementation evidence.
5. Write a **new** `handoffs/<timestamp>_<agent>_<unique>.md` file with task, result, evidence, risks and next steps; do not edit handoffs created by other agents.
6. For status/decision changes: propose a diff, seek user approval, and submit via reviewed commit or PR.

## Roles (defaults, not platform restrictions)

- ChatGPT: plan, clarify decisions, independently assess evidence; can read/write only through authorized tools.
- WorkBuddy: inspect real software source code, implement approved work, report actual command outputs.
- Codex: independent code and regression review; review evidence, don't rubber-stamp another agent.
- User: owner of priorities, sensitive data, release permissions and final sign-off.

## Hard constraints

- No secret tokens or personal/company-sensitive raw records in either public or private context repo.
- No `git push --force`, no automated trades, no changes to product source repos during a connection test.
- Don't merge conflicting opinions by silently changing approved decisions.
- New working copy must fetch latest history before reading or submitting reports.
- Connection test success means a *real* read + write + read-back on each platform, not a file merely being visible to one agent.
