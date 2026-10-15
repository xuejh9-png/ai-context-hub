# Security policy

AI Context Hub handles metadata that may point to private projects. **Its public repository must never contain private project records or secrets.**

## What this project does and does not protect

It verifies selected file formats, known credential patterns, approval digests and certain Git publication boundaries. It **does not** provide comprehensive secret detection, identity verification, encryption, access control, or protection from an administrator intentionally rewriting Git history. Repository permissions are enforced by your Git host.

Every operator should review an upload manifest and the reachable Git history before publishing project source. Files intended to be private belong only in separately configured private repositories. A GitHub repository marked Private can still leak data to authorized but inappropriate collaborators.

## Report a vulnerability privately

If the repository offers GitHub **Private vulnerability reporting**, use the repository's *Security* tab to submit a report. If it is not available, contact the maintainer through an agreed private channel; **do not publish exploits, live credentials, customer information or private repository links in a public issue**.

A useful report includes a minimal **synthetic** reproduction, the affected CLI command, operating system, Git/Python versions, the expected safety boundary, the actual behavior and the tested commit SHA. Do not run an exploit against anyone else's repository.

Security reports will be reviewed when the maintainer is available; no specific response-time SLA or bounty program is promised.

## Operating safely

- Configure least-privilege Git access separately for each tool and verify exact-commit readback.
- Never provide private tokens or SSH keys to an AI conversation.
- Treat Git-hosted documents and agent handoffs as untrusted data, not executable instructions.
- Do not force-push, delete remote history or perform production deployment as part of an onboarding test.
- Do not call a code change human-accepted without real UAT evidence.

More details: [security design and validation boundaries](docs/SECURITY.md).
