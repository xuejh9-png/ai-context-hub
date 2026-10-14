# UAT feedback <YYYYMMDDTHHMMSSffffffZ>_<reporter>_<unique-id>

- Project: <slug>
- Feedback ID: <id>
- Task: <task-id>
- Reporter: <reporter>
- Reported (UTC): <timestamp>
- Severity: low | medium | high | critical
- Source repo: <source repository URL>
- Tested commit / build: <exact commit SHA or build identifier that was actually tested>
- Runtime environment: <OS, device, app/build version, data set>
- Screenshot: assets/<name> (SHA-256: <hash>; origin: <where it came from>) | None
- Related PR: <pull request URL> | NOT_OPENED
- Related handoff: <handoff id> | NOT_LINKED

## Reproducible steps
1. ...
2. ...
3. ...

## Expected result
What should happen.

## Observed result
What actually happened. Separate observation from interpretation.

## Impact
Who or what is blocked, and how severe. Use "Not assessed." if unknown.

## Logs / references
Console output, run logs, timestamps. Use "None." if there are none.

## Status history (append-only — never rewrite earlier entries)
- <timestamp> | reported | <reporter> | initial report

---

Notes for the reporter:

* The record is created as `reported`. The **current status is the last line** of the status
  history, so earlier entries are never edited.
* Add transitions with `ach uat-status`, then publish with `ach uat-publish`. A published
  record may gain status lines and new screenshots; rewriting or deleting published content
  is refused so a reviewer can always see the original report.
* Attach a screenshot only when it is intentionally approved. Crop or redact credentials,
  customer data, account names and internal URLs first; the file is validated for size,
  type, name and hash, not for sensitive content.
* Record the commit you actually tested. "Latest main" is not evidence.
