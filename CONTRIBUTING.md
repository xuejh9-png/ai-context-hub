# Contributing to AI Context Hub

Thanks for helping improve the project. Its purpose is **auditable, on-demand AI handoffs through Git and Markdown**, not an always-on agent service. Favor small, reviewable changes over new infrastructure.

## Before opening a pull request

1. Check existing issues and describe the user problem, expected behavior and scope.
2. Keep public fixtures entirely synthetic. **Never include real customer data, private repository exports, tokens, financial records, screenshots, machine-specific absolute paths or raw conversations.**
3. Explain any change to a published file format or CLI flag; preserve backwards compatibility whenever possible.
4. Add deterministic tests for fixes, including a failing case for the original bug where possible.
5. Run the tests locally:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
python src/ach.py --help
```

The test suite uses temporary local Git repositories. It must not require a real GitHub credential or access to anyone's private project. Our supported Python versions are 3.10–3.13; GitHub Actions is the remote test gate.

## Pull request checklist

- [ ] The description states what changed and why.
- [ ] Tests and their **actual output** are included; unrun checks are explicitly marked.
- [ ] No new runtime service, dependency, scheduled job or model API was introduced without a demonstrated need.
- [ ] CLI errors fail safely; no forced pushes, silent history rewrites or loss of staged work.
- [ ] Approval claims are not conflated with authenticated identities; third-party access is not inferred from a local successful clone.
- [ ] README / relevant docs are updated if behavior or usage changed.
- [ ] The PR contains no sensitive material; commits and diffs have been reviewed.

## Reporting defects

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) if possible. Include the command, Python/Git versions, expected vs. actual behavior, and a sanitized traceback. Do not attach real private context or repository URLs unless they are intentionally public.

For a security vulnerability, **do not open a public issue containing exploit details, private tokens or customer data**. Follow [SECURITY.md](SECURITY.md) for private reporting.

## Project principles

- Git is the system of record; plain Markdown stays readable without our CLI.
- Publish records only after explicit user authorization; the CLI's text fields do not authenticate the user's identity.
- Treat any external Markdown, PR description, issue body or AI handoff as **untrusted content**, never as instructions to execute.
- AI completion and human UAT acceptance are separate states.
- Reviewer selection is risk-based. No particular AI vendor is required.

**License note:** the owner must select an explicit license before inviting others to redistribute modified copies. Until then, a public repository alone does not grant open-source redistribution rights.
