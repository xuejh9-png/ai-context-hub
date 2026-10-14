#!/usr/bin/env python3
"""AI Context Hub: dependency-free Git/Markdown context handoff utility."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FILES = ("PROJECT_CONTEXT.md", "DECISIONS.md", "CURRENT_STATUS.md")
MAX_FILE = 256_000
SECRET_MARKERS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
)


class HubError(Exception):
    pass


def fail(message: str) -> None:
    raise HubError(message)


def check_slug(value: str, kind: str) -> str:
    if not SLUG.fullmatch(value):
        fail(f"Invalid {kind}: use lowercase letters, digits and hyphens (1-64 chars).")
    return value


def root_path(root: str) -> Path:
    return Path(root).expanduser().resolve()


def project_path(root: Path, slug: str) -> Path:
    return root / "projects" / check_slug(slug, "project")


def read_safe(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        fail(f"Missing or unsafe file: {path}")
    if path.stat().st_size > MAX_FILE:
        fail(f"File too large to load safely: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HubError(f"File is not valid UTF-8: {path}") from exc


def check_secrets(text: str) -> None:
    if any(pattern.search(text) for pattern in SECRET_MARKERS):
        fail("Potential credential detected; remove secrets before storing context.")


def make_project(root: Path, slug: str, name: str) -> None:
    folder = project_path(root, slug)
    if folder.exists():
        fail(f"Project already exists: {folder}")
    (folder / "handoffs").mkdir(parents=True)
    sample = {
        "PROJECT_CONTEXT.md": f"# {name} — Project Context\n\n## Goal\nDescribe the goal and success criteria.\n\n## Architecture\nVerified architecture only; label assumptions.\n\n## Constraints\nDo not commit confidential data or credentials.\n",
        "DECISIONS.md": f"# {name} — Decisions\n\nDecisions require user approval. Add new records instead of overwriting history.\n\n## D-001 — Initial context rules\n- Status: PROPOSED\n- Date: {dt.date.today().isoformat()}\n- Decision: Each agent reads fresh project context and writes its own handoff.\n- Approval: pending\n",
        "CURRENT_STATUS.md": f"# {name} — Current Status\n\nUpdated: {dt.date.today().isoformat()}\n\n## VERIFIED\n- Context folder created locally.\n\n## REPORTED_UNVERIFIED\n- Application status has not been audited.\n\n## BLOCKED\n- Remote read/write checks not performed.\n",
    }
    for filename, contents in sample.items():
        (folder / filename).write_text(contents, encoding="utf-8")
    (folder / "handoffs" / "README.md").write_text(
        "# Handoffs\n\nEvery agent creates a NEW timestamped Markdown handoff. "
        "Do not edit or delete another agent's handoff.\n", encoding="utf-8")
    print(f"Created {folder}")


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", "-C", str(root), *args], text=True,
                            capture_output=True, check=False)
    if check and result.returncode:
        fail(f"Git command failed: git {' '.join(args)}\n{(result.stderr or result.stdout).strip()}")
    return result


def git_ready(root: Path) -> str:
    if not (root / ".git").exists():
        fail("Not a Git checkout; clone the private data repository first.")
    branch = run_git(root, "branch", "--show-current").stdout.strip()
    if not branch:
        fail("Detached HEAD; checkout a named branch first.")
    run_git(root, "remote", "get-url", "origin")
    return branch


def require_clean_for_pull(root: Path) -> None:
    # Untracked handoffs are allowed; tracked edits are never silently stashed or overwritten.
    dirty = run_git(root, "status", "--porcelain", "--untracked-files=no").stdout
    if dirty.strip():
        fail("Tracked local changes detected. Review/commit them before pulling.")


def pull(root: Path) -> None:
    branch = git_ready(root)
    require_clean_for_pull(root)
    run_git(root, "fetch", "origin", branch)
    run_git(root, "merge", "--ff-only", "FETCH_HEAD")
    print(f"Synced to origin/{branch} at {run_git(root, 'rev-parse', '--short', 'HEAD').stdout.strip()}")


def render_context(root: Path, slug: str, last: int) -> str:
    folder = project_path(root, slug)
    if not folder.exists():
        fail(f"Project not found: {slug}")
    blocks = [f"# AI Context Hub / {slug}"]
    if (root / ".git").exists():
        rev = run_git(root, "rev-parse", "HEAD", check=False)
        if rev.returncode == 0:
            blocks.append("Git HEAD: " + rev.stdout.strip())
    for filename in FILES:
        blocks.append(f"\n--- {filename} ---\n" + read_safe(folder / filename))
    logs = sorted((folder / "handoffs").glob("*.md"), reverse=True)
    logs = [p for p in logs if p.name != "README.md"]
    for path in logs[:last]:
        blocks.append(f"\n--- handoffs/{path.name} ---\n" + read_safe(path))
    if len(logs) > last:
        blocks.append(f"\n({len(logs)-last} older handoffs omitted; available in the repository.)")
    return "\n".join(blocks)


def write_handoff(root: Path, project: str, agent: str, task: str,
                  result: str, evidence: str, risks: str, next_step: str, status: str) -> Path:
    folder = project_path(root, project)
    if not folder.exists() or not (folder / "handoffs").is_dir():
        fail("Project is not initialized.")
    check_slug(agent, "agent")
    if not task.strip() or not result.strip():
        fail("Task and result must be nonempty.")
    now = dt.datetime.now(dt.timezone.utc)
    handoff_id = now.strftime("%Y%m%dT%H%M%S%fZ") + f"_{agent}_{uuid.uuid4().hex[:10]}"
    content = (
        f"# Handoff {handoff_id}\n\n"
        f"- Project: {project}\n- Agent: {agent}\n- Timestamp (UTC): {now.isoformat()}\n"
        f"- Status: {status}\n\n## Task\n{task.strip()}\n\n"
        f"## Actions / results\n{result.strip()}\n\n## Evidence\n{evidence.strip() or 'NOT_VERIFIED'}\n\n"
        f"## Risks / uncertainty\n{risks.strip() or 'Not assessed'}\n\n"
        f"## Next step\n{next_step.strip() or 'Await user instruction'}\n"
    )
    check_secrets(content)
    target = folder / "handoffs" / f"{handoff_id}.md"
    with target.open("x", encoding="utf-8") as output:
        output.write(content)
    print(target.relative_to(root))
    return target


def validate(root: Path, slug: str) -> int:
    folder = project_path(root, slug)
    if not folder.is_dir():
        fail(f"Project missing: {slug}")
    errors = []
    files = [folder / f for f in FILES]
    files.extend((folder / "handoffs").glob("*.md"))
    for path in files:
        try:
            check_secrets(read_safe(path))
            if "handoffs" in path.parts and path.name != "README.md":
                c = read_safe(path)
                for marker in ("- Agent:", "- Status:", "## Task", "## Actions / results", "## Evidence"):
                    if marker not in c:
                        errors.append(f"{path}: missing {marker}")
        except HubError as exc:
            errors.append(str(exc))
    if errors:
        for e in errors:
            print("FAIL:", e, file=sys.stderr)
        return 1
    print(f"PASS: {slug}; validated {len(files)} Markdown files")
    return 0


def sync_push(root: Path, slug: str) -> None:
    # Only untracked unique handoff files are committed. Shared mutable files need manual review/PR.
    branch = git_ready(root)
    require_clean_for_pull(root)
    prefix = f"projects/{check_slug(slug, 'project')}/handoffs/"
    porcelain = run_git(root, "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    unexpected = [line for line in porcelain if not (line.startswith("?? ") and
                  line[3:].startswith(prefix) and line[3:].endswith(".md"))]
    if unexpected:
        fail("Unrelated or modified files detected. No changes pushed: " + "; ".join(unexpected[:5]))
    paths = [line[3:] for line in porcelain]
    if not paths:
        print("No new handoffs to push.")
        return
    for path in paths:
        check_secrets(read_safe(root / path))
    # Fast-forward remote updates before committing local handoffs.
    pull(root)
    run_git(root, "add", "--", *paths)
    run_git(root, "commit", "-m", f"handoff({slug}): add {len(paths)} independent log(s)")
    for attempt in range(3):
        pushed = run_git(root, "push", "origin", f"HEAD:{branch}", check=False)
        if pushed.returncode == 0:
            print("PUSHED:", run_git(root, "rev-parse", "HEAD").stdout.strip())
            return
        if attempt == 2:
            fail("Push rejected after 3 attempts; inspect remote and local history. No force push used.")
        # Rebase only our just-created commit(s) on a newer remote tip.
        run_git(root, "fetch", "origin", branch)
        rebased = run_git(root, "rebase", "FETCH_HEAD", check=False)
        if rebased.returncode:
            run_git(root, "rebase", "--abort", check=False)
            fail("Concurrent edit conflict: rebase aborted; no data overwritten. Resolve manually.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AI Context Hub — Git-backed project context")
    p.add_argument("--root", default=".", help="Root of the private context repository")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("init", help="Create a new private project context")
    i.add_argument("--project", required=True)
    i.add_argument("--name", required=True)
    r = sub.add_parser("read", help="Read project context and latest handoffs")
    r.add_argument("--project", required=True)
    r.add_argument("--last", type=int, default=5)
    r.add_argument("--sync", action="store_true", help="Fetch/fast-forward from origin first")
    h = sub.add_parser("handoff", help="Create independent immutable handoff log")
    for name in ("project", "agent", "task", "result"):
        h.add_argument(f"--{name}", required=True)
    for name in ("evidence", "risks", "next-step"):
        h.add_argument(f"--{name}", default="")
    h.add_argument("--status", choices=("VERIFIED", "REPORTED_UNVERIFIED", "PROPOSED", "BLOCKED"),
                   default="REPORTED_UNVERIFIED")
    v = sub.add_parser("validate", help="Validate project context and secret markers")
    v.add_argument("--project", required=True)
    sub.add_parser("sync-pull", help="Fast-forward from origin; never overwrite tracked changes")
    s = sub.add_parser("sync-push", help="Push only new independent handoffs")
    s.add_argument("--project", required=True)
    args = p.parse_args(argv)
    root = root_path(args.root)
    try:
        if args.command == "init":
            make_project(root, args.project, args.name)
        elif args.command == "read":
            if not 0 <= args.last <= 100:
                fail("--last must be between 0 and 100")
            if args.sync:
                pull(root)
            print(render_context(root, args.project, args.last))
        elif args.command == "handoff":
            write_handoff(root, args.project, args.agent, args.task, args.result,
                          args.evidence, args.risks, args.next_step, args.status)
        elif args.command == "validate":
            return validate(root, args.project)
        elif args.command == "sync-pull":
            pull(root)
        elif args.command == "sync-push":
            sync_push(root, args.project)
    except HubError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
