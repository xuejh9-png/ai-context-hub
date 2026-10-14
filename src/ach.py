#!/usr/bin/env python3
"""AI Context Hub: dependency-free Git/Markdown context handoff utility.

v0.2 adds three cooperating, reviewable artifacts on top of the v0.1 handoff loop:

* an approved **task packet** (``tasks/<task-id>/``) published only after a human
  approval record exists, with fail-closed Git identity/remote/permission checks;
* an **image asset handoff** (``assets/`` + ``ASSETS.md``) whose SHA-256 manifest is
  re-verified at publish and read-back time;
* a **UAT feedback loop** (``uat/<feedback-id>/``) whose records are append-only, so a
  published defect report can gain status history without rewriting earlier evidence.

v0.3 adds **application-source repository onboarding**: a read-only inspection, a
human-approved file manifest, a non-destructive first upload into a separate private
repository, an independent fresh-clone read-back, and a per-tool read-access record that
keeps "this machine can read it" separate from "another AI tool can read it".

Everything remains plain UTF-8 Markdown inside an ordinary Git repository. No server,
database, queue, background agent or chat capture is involved.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fnmatch
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FILES = ("PROJECT_CONTEXT.md", "DECISIONS.md", "CURRENT_STATUS.md")
TASK_FILES = ("BRIEF.md", "ACCEPTANCE.md", "ASSETS.md")
UAT_FILES = ("UAT_FEEDBACK.md", "ASSETS.md")
APPROVAL_FILE = "APPROVAL.md"
MAX_FILE = 256_000
MAX_ASSET = 5_000_000
ASSET_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}\.(?:png|jpe?g|gif|webp)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CODE_SHA = re.compile(r"^[0-9a-f]{7,40}$")
UAT_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z_[a-z0-9][a-z0-9-]{0,63}_[0-9a-f]{10}$")
HANDOFF_STATUS = ("VERIFIED", "REPORTED_UNVERIFIED", "PROPOSED", "BLOCKED")
UAT_STATUS = ("reported", "reproduced", "fixed", "re-tested")
UAT_SEVERITY = ("low", "medium", "high", "critical")
HANDOFF_IMPL_MARKERS = (
    "- Source repo:", "- Branch:", "- Code SHA:", "- PR:",
    "- Build / run instructions:", "- Test evidence:", "- Human acceptance:",
)
BRIEF_MARKERS = (
    "- Task ID:", "- Revision:", "- Accountable AI:", "- Approval:", "- Approved by:",
    "- Implementation target (source repo):", "## Approved scope", "## Out of scope",
    "## Expected results",
)
UAT_MARKERS = (
    "- Feedback ID:", "- Task:", "- Reporter:", "- Severity:", "- Source repo:",
    "- Tested commit / build:", "- Runtime environment:", "- Screenshot:",
    "## Reproducible steps", "## Expected result", "## Observed result", "## Status history",
)
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


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp(moment: dt.datetime | None = None) -> str:
    return (moment or now_utc()).isoformat(timespec="seconds")


def check_slug(value: str, kind: str) -> str:
    if not SLUG.fullmatch(value):
        fail(f"Invalid {kind}: use lowercase letters, digits and hyphens (1-64 chars).")
    return value


def check_uat_id(value: str) -> str:
    if not UAT_ID.fullmatch(value):
        fail("Invalid feedback id; use an id created by uat-new.")
    return value


def one_line(value: str, name: str) -> str:
    value = value.strip()
    if not value or "\n" in value or "\r" in value:
        fail(f"{name} must be one nonempty line.")
    return value


def safe_rel(rel: str) -> bool:
    """Reject absolute, empty, '.' and '..' path components (path traversal guard)."""
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", rel):
        return False
    return not any(part in ("", ".", "..") for part in rel.split("/"))


def root_path(root: str) -> Path:
    return Path(root).expanduser().resolve()


def project_path(root: Path, slug: str) -> Path:
    return root / "projects" / check_slug(slug, "project")


def require_workspace_path(root: Path, path: Path) -> None:
    """Reject a managed path that escapes the checkout through a symlinked parent."""
    root = root.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        fail(f"Path escapes the repository: {path}")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            fail(f"Symlinks are not allowed in managed paths: {current}")


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
    if secret_hit(text):
        fail("Potential credential detected; remove secrets before storing context.")


def secret_hit(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_MARKERS)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_magic_ok(name: str, data: bytes) -> bool:
    suffix = Path(name).suffix.lower()
    if suffix == ".png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return False
        position = 8
        chunks: list[bytes] = []
        while position + 12 <= len(data):
            length = int.from_bytes(data[position:position + 4], "big")
            end = position + 12 + length
            if end > len(data):
                return False
            kind = data[position + 4:position + 8]
            payload = data[position + 8:position + 8 + length]
            expected = int.from_bytes(data[position + 8 + length:end], "big")
            import zlib
            if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected:
                return False
            chunks.append(kind)
            if len(chunks) == 1 and (kind != b"IHDR" or length != 13 or
                                     int.from_bytes(payload[:4], "big") == 0 or
                                     int.from_bytes(payload[4:8], "big") == 0):
                return False
            position = end
            if kind == b"IEND":
                return length == 0 and position == len(data) and b"IDAT" in chunks
        return False
    if suffix in (".jpg", ".jpeg"):
        return len(data) >= 4 and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    if suffix == ".gif":
        return (len(data) >= 14 and data.startswith((b"GIF87a", b"GIF89a")) and
                int.from_bytes(data[6:8], "little") > 0 and
                int.from_bytes(data[8:10], "little") > 0 and data.endswith(b"\x3b"))
    if suffix == ".webp":
        return (len(data) >= 20 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and
                int.from_bytes(data[4:8], "little") == len(data) - 8 and
                data[12:16] in (b"VP8 ", b"VP8L", b"VP8X"))
    return False


def validate_asset_file(path: Path) -> None:
    """Assets are the only binary payload the CLI ever publishes."""
    if path.is_symlink() or not path.is_file():
        fail(f"Missing or unsafe asset: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_ASSET:
        fail(f"Asset size must be 1..{MAX_ASSET} bytes: {path} ({size} bytes)")
    if not ASSET_NAME.fullmatch(path.name):
        fail(f"Unsafe asset name (lowercase, png/jpeg/gif/webp): {path.name}")
    data = path.read_bytes()
    if not image_magic_ok(path.name, data):
        fail(f"Asset content does not match an allowed image type: {path}")
    check_secrets(data.decode("latin-1"))


def is_asset_path(rel: str) -> bool:
    parts = rel.split("/")
    return (safe_rel(rel) and len(parts) >= 2 and parts[-2] == "assets"
            and bool(ASSET_NAME.fullmatch(parts[-1])))


def parse_fields(text: str, keys: tuple[str, ...]) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        for key in keys:
            if line.startswith(key + " ") or line.startswith(key):
                found[key] = line[len(key):].strip()
    return found


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


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", "-C", str(root), *args], text=True, encoding="utf-8",
                            errors="surrogateescape", capture_output=True, check=False)
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


def require_git_identity(root: Path) -> None:
    """Fail closed: without a usable identity Git would commit under a wrong/absent author."""
    for ident in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        result = run_git(root, "var", ident, check=False)
        if result.returncode or "@" not in result.stdout:
            fail(f"Git identity is unavailable ({ident}); publication is blocked. "
                 "Configure user.name/user.email for this checkout.")


def require_clean_for_pull(root: Path, allow_prefix: str | None = None,
                           allowed=None) -> None:
    """Untracked files are allowed; tracked edits are never silently stashed or overwritten.

    ``allow_prefix``/``allowed`` narrow the exception to append-only UAT records, whose
    published history may gain a new status line but may never be rewritten.
    """
    porcelain = run_git(root, "status", "--porcelain", "-z", "--untracked-files=no").stdout
    for entry in (item for item in porcelain.split("\0") if item):
        path = entry[3:]
        if allow_prefix and allowed and path.startswith(allow_prefix) and allowed(path):
            continue
        fail("Tracked local changes detected. Review/commit them before pulling.")


def pull(root: Path) -> None:
    branch = git_ready(root)
    with sync_lock(root):
        require_clean_for_pull(root)
        run_git(root, "fetch", "origin", branch)
        run_git(root, "merge", "--ff-only", "FETCH_HEAD")
        print(f"Synced to origin/{branch} at {run_git(root, 'rev-parse', '--short', 'HEAD').stdout.strip()}")


@contextlib.contextmanager
def sync_lock(root: Path):
    lock = root / run_git(root, "rev-parse", "--git-path", "ach-sync.lock").stdout.strip()
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        fail("Another sync owns ach-sync.lock. Retry after it finishes; inspect stale locks manually.")
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


# ---------------------------------------------------------------------------
# Publication core (shared by handoffs, task packets and UAT records)
# ---------------------------------------------------------------------------

def local_files(root: Path, prefix: str) -> list[str]:
    base = root / prefix
    require_workspace_path(root, base)
    if not base.is_dir():
        return []
    results = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            fail(f"Symlinks are not allowed inside a published packet: {path}")
        if path.is_file():
            results.append(path.relative_to(root).as_posix())
    return results


def remote_files(root: Path, prefix: str) -> list[str]:
    output = run_git(root, "ls-tree", "-r", "-z", "--name-only", "FETCH_HEAD", "--", prefix).stdout
    return sorted(item for item in output.split("\0") if item)


def remote_state(root: Path, prefix: str) -> str:
    """Compare a local packet against FETCH_HEAD: absent | identical | different."""
    remote = remote_files(root, prefix)
    if not remote:
        return "absent"
    if remote != local_files(root, prefix):
        return "different"
    for rel in remote:
        if run_git(root, "rev-parse", f"FETCH_HEAD:{rel}").stdout.strip() != \
                run_git(root, "hash-object", str(root / rel)).stdout.strip():
            return "different"
    return "identical"


def pending_paths(root: Path, prefix: str, allowed, region: str,
                  allow_modified: bool = False) -> set[str]:
    """Check every unpublished commit, including content hidden by later edits."""
    paths: set[str] = set()
    commits = run_git(root, "rev-list", "FETCH_HEAD..HEAD").stdout.splitlines()
    for commit in commits:
        parents = run_git(root, "rev-list", "--parents", "-n", "1", commit).stdout.split()
        changes = run_git(root, "diff-tree", "--root", "--no-commit-id", "--no-renames",
                          "--name-status", "-r", "-z", *(["--cc"] if len(parents) > 2 else []),
                          commit).stdout.rstrip("\0").split("\0")
        if changes == [""]:
            continue
        # A merge may incorporate approved remote changes, but must not resolve/edit files.
        if len(parents) > 2:
            fail("Unreviewed merge resolution in unpublished history. Review manually.")
        for status, path in zip(changes[::2], changes[1::2]):
            permitted = status == "A" or (allow_modified and status == "M")
            if not permitted or not allowed(path):
                fail(f"Unrelated or modified unpublished history detected. No {region} pushed.")
            mode = run_git(root, "ls-tree", commit, "--", path).stdout.split()[0]
            if mode not in ("100644", "100755"):
                fail(f"Unsafe {region} entry in unpublished history.")
            size = int(run_git(root, "cat-file", "-s", f"{commit}:{path}").stdout)
            if size > (MAX_ASSET if is_asset_path(path) else MAX_FILE):
                fail(f"{region.capitalize()} entry too large in unpublished history.")
            if allow_modified and status == "M":
                if is_asset_path(path) or len(parents) < 2:
                    fail(f"Published {region} binary/history may not be rewritten.")
                old = run_git(root, "cat-file", "blob", f"{parents[1]}:{path}").stdout
                new = run_git(root, "cat-file", "blob", f"{commit}:{path}").stdout
                verify_uat_text_append(path, old, new)
            if not is_asset_path(path):
                check_secrets(run_git(root, "cat-file", "blob", f"{commit}:{path}").stdout)
            paths.add(path)
    return paths


def integrate_remote(root: Path, local_paths: set[str]) -> None:
    base = run_git(root, "merge-base", "HEAD", "FETCH_HEAD").stdout.strip()
    remote_paths = set(run_git(root, "diff", "--name-only", "-z", base, "FETCH_HEAD")
                       .stdout.rstrip("\0").split("\0"))
    if local_paths & remote_paths:
        fail("Concurrent filename conflict. Local files/commits retained; review manually.")
    # Append a merge for independent histories; never rewrite/drop the local log commit.
    merged = run_git(root, "merge", "--no-edit", "FETCH_HEAD", check=False)
    if merged.returncode:
        run_git(root, "merge", "--abort", check=False)
        fail("Remote integration failed. Local commits retained; resolve manually.")


def publish_paths(root: Path, *, prefix: str, allowed, message, region: str,
                  allow_modified: bool = False) -> None:
    """Commit and push only the paths a reviewable workflow is permitted to publish.

    Never force-pushes. On any failure the local bytes and commits are preserved so the
    operator can inspect and retry instead of losing evidence.
    """
    branch = git_ready(root)
    require_clean_for_pull(root, allow_prefix=prefix if allow_modified else None,
                           allowed=allowed)
    porcelain = run_git(root, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    selected: list[str] = []
    unexpected: list[str] = []
    for entry in (item for item in porcelain.split("\0") if item):
        status, path = entry[:2], entry[3:]
        if status == "??" and safe_rel(path) and allowed(path):
            selected.append(path)
        elif allow_modified and status == " M" and safe_rel(path) and allowed(path):
            selected.append(path)
        else:
            unexpected.append(entry)
    if unexpected:
        fail(f"Unrelated or modified files detected. No {region} pushed: "
             + "; ".join(unexpected[:5]))
    for path in selected:
        if is_asset_path(path):
            validate_asset_file(root / path)
        else:
            check_secrets(read_safe(root / path))
    run_git(root, "fetch", "origin", branch)
    pending = pending_paths(root, prefix, allowed, region, allow_modified)
    if selected or pending:
        require_git_identity(root)
    integrate_remote(root, pending | set(selected))
    if selected:
        try:
            run_git(root, "add", "--", *selected)
            run_git(root, "commit", "--only", "-m", message(len(selected)), "--", *selected)
        except HubError:
            # The index started clean. Unstage only our files; retain working bytes.
            run_git(root, "restore", "--staged", "--", *selected)
            raise
    if not selected and not pending:
        print(f"No new or pending {region} to push.")
        return
    for attempt in range(3):
        require_clean_for_pull(root)
        pending = pending_paths(root, prefix, allowed, region, allow_modified)
        pushed = run_git(root, "push", "origin", f"HEAD:{branch}", check=False)
        if pushed.returncode == 0:
            print("PUSHED:", run_git(root, "rev-parse", "HEAD").stdout.strip())
            return
        if attempt == 2:
            fail(f"Push rejected after 3 attempts; {region} remains committed locally. "
                 "Fix connectivity/permissions and rerun. No force push used.")
        run_git(root, "fetch", "origin", branch)
        integrate_remote(root, pending)


def is_handoff(path: str, prefix: str) -> bool:
    name = path.removeprefix(prefix)
    return (safe_rel(path) and path.startswith(prefix) and "/" not in name
            and name.endswith(".md") and name != "README.md")


def sync_push(root: Path, slug: str) -> None:
    git_ready(root)
    with sync_lock(root):
        prefix = f"projects/{check_slug(slug, 'project')}/handoffs/"
        publish_paths(root, prefix=prefix, allowed=lambda path: is_handoff(path, prefix),
                      region="handoff",
                      message=lambda count: f"handoff({slug}): add {count} independent log(s)")


# ---------------------------------------------------------------------------
# Task packets (P0)
# ---------------------------------------------------------------------------

def task_root(root: Path, slug: str, task_id: str) -> Path:
    return project_path(root, slug) / "tasks" / check_slug(task_id, "task id")


def task_rel(slug: str, task_id: str) -> str:
    return f"projects/{check_slug(slug, 'project')}/tasks/{check_slug(task_id, 'task id')}/"


def is_task_file(rel: str, prefix: str) -> bool:
    if not safe_rel(rel) or not rel.startswith(prefix):
        return False
    rest = rel[len(prefix):]
    return rest in TASK_FILES or rest == APPROVAL_FILE or is_asset_path(rel)


def task_new(root: Path, slug: str, task_id: str, *, title: str, revision: str,
             accountable: str, source_repo: str, baseline_sha: str, scope: str,
             out_of_scope: str, expected: str, request: str, evidence: str,
             criteria: list[str]) -> Path:
    folder = task_root(root, slug, task_id)
    require_workspace_path(root, folder)
    if not (project_path(root, slug) / "handoffs").is_dir():
        fail("Project is not initialized.")
    if folder.exists():
        fail(f"Task already exists (never overwritten): {folder}")
    for name, value in (("--title", title), ("--accountable", accountable),
                        ("--source-repo", source_repo), ("--scope", scope),
                        ("--expected", expected)):
        if not value.strip():
            fail(f"{name} must be nonempty; a usable packet needs an approved scope.")
    check_slug(accountable, "accountable agent")
    created = stamp()
    brief = (
        f"# Task {task_id} — {title.strip()}\n\n"
        f"- Project: {slug}\n"
        f"- Task ID: {task_id}\n"
        f"- Revision: {revision.strip() or 'v1'}\n"
        f"- Accountable AI: {accountable}\n"
        f"- Created (UTC): {created}\n"
        f"- Implementation target (source repo): {source_repo.strip()}\n"
        f"- Baseline SHA: {baseline_sha.strip() or 'UNKNOWN'}\n"
        f"- Approval: PENDING\n"
        f"- Approved by: (none)\n"
        f"- Approved (UTC): (none)\n\n"
        f"## Requested change\n{request.strip() or 'See approved scope.'}\n\n"
        f"## Approved scope\n{scope.strip()}\n\n"
        f"## Out of scope\n{out_of_scope.strip() or 'None stated.'}\n\n"
        f"## Expected results\n{expected.strip()}\n\n"
        f"## Evidence links\n{evidence.strip() or 'None yet.'}\n"
    )
    default_criteria = [
        "Implementation matches the approved scope in BRIEF.md.",
        "Automated tests were run and their real output is recorded in the handoff.",
        "Human UAT was performed on the exact tested commit (see UAT feedback records).",
    ]
    criteria = [item.strip() for item in criteria if item.strip()] or default_criteria
    acceptance = ("# Acceptance criteria — " + task_id +
                  "\n\nEvery criterion must be verifiable by a command, an observable artifact or an\n"
                  "explicit human check. AI implementation does NOT tick these boxes; human UAT does.\n\n"
                  + "\n".join(f"- [ ] AC-{i}: {item}" for i, item in enumerate(criteria, 1)) + "\n")
    assets = (f"# Approved assets — {task_id}\n\n"
              "Only intentionally approved evidence assets appear here. Never add private or\n"
              "third-party images without the owner's approval. The SHA-256 manifest is re-verified\n"
              "at publish and read-back time.\n\n"
              "No asset is registered yet. Add one with:\n\n"
              f"```bash\nach --root . task-asset --project {slug} --task {task_id} "
              "--file <path> --origin <where it came from> --approved-by <user>\n```\n")
    for filename, contents in (("BRIEF.md", brief), ("ACCEPTANCE.md", acceptance),
                               ("ASSETS.md", assets)):
        check_secrets(contents)
    folder.mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "BRIEF.md").write_text(brief, encoding="utf-8")
    (folder / "ACCEPTANCE.md").write_text(acceptance, encoding="utf-8")
    (folder / "ASSETS.md").write_text(assets, encoding="utf-8")
    print(f"Created task packet {task_rel(slug, task_id)} (status: DRAFT, approval PENDING)")
    return folder


def task_approve(root: Path, slug: str, task_id: str, *, approved_by: str,
                 statement: str) -> Path:
    """Serialize the multi-file approval write with all publication operations."""
    git_ready(root)
    with sync_lock(root):
        return _task_approve(root, slug, task_id, approved_by=approved_by,
                             statement=statement)


def _task_approve(root: Path, slug: str, task_id: str, *, approved_by: str,
                  statement: str) -> Path:
    """Record the human approval that publication depends on. Runs at most once per task."""
    folder = task_root(root, slug, task_id)
    require_workspace_path(root, folder)
    brief_path = folder / "BRIEF.md"
    if not brief_path.is_file():
        fail(f"Task packet not found: {task_rel(slug, task_id)}")
    approved_by = one_line(approved_by, "--approved-by")
    statement = one_line(statement, "--statement")
    if (folder / APPROVAL_FILE).exists():
        fail(f"{APPROVAL_FILE} already exists; an approved task is never re-approved or overwritten. "
             "Create a new task id or revision instead.")
    brief = read_safe(brief_path)
    if "- Approval: APPROVED" in brief:
        fail("Brief is already APPROVED but has no approval record. Inspect the packet manually.")
    if "- Approval: PENDING" not in brief:
        fail("Brief is not in PENDING state; refusing to guess its approval status.")
    issues = packet_issues(root, slug, task_id, require_approved=False)
    if issues:
        fail("Task packet is not internally valid and cannot be approved: " + "; ".join(issues[:3]))
    approved = (brief
                .replace("- Approval: PENDING", "- Approval: APPROVED", 1)
                .replace("- Approved by: (none)", f"- Approved by: {approved_by}", 1)
                .replace("- Approved (UTC): (none)", f"- Approved (UTC): {stamp()}", 1))
    check_secrets(approved)
    check_secrets(statement)
    record = (f"# Approval record — {task_id}\n\n"
              f"- Project: {slug}\n"
              f"- Task ID: {task_id}\n"
              f"- Approved by: {approved_by}\n"
              f"- Approved (UTC): {stamp()}\n"
              f"- BRIEF.md SHA-256: {sha256_text(approved)}\n"
              f"- ACCEPTANCE.md SHA-256: {sha256_text(read_safe(folder / 'ACCEPTANCE.md'))}\n"
              f"- ASSETS.md SHA-256: {sha256_text(read_safe(folder / 'ASSETS.md'))}\n"
              f"- Approval statement: {statement}\n")
    brief_path.write_text(approved, encoding="utf-8")
    with (folder / APPROVAL_FILE).open("x", encoding="utf-8") as handle:
        handle.write(record)
    print(f"Approved {task_rel(slug, task_id)} by {approved_by} "
          f"(BRIEF.md SHA-256 {sha256_text(approved)[:12]}…)")
    return folder / APPROVAL_FILE


def parse_assets(text: str) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = re.fullmatch(r"## (assets/[A-Za-z0-9._-]{1,80})", line.strip())
        if heading:
            current = heading.group(1)
            entries[current] = {}
            continue
        if line.startswith("## "):
            current = None
            continue
        if current and line.startswith("- "):
            key, separator, value = line[2:].partition(": ")
            if separator:
                entries[current][key.strip()] = value.strip()
    return entries


def asset_manifest_issues(root: Path, prefix: str, manifest_path: Path) -> list[str]:
    """Verify that the manifest and the exact asset set agree in both directions."""
    issues: list[str] = []
    try:
        manifest_text = read_safe(manifest_path)
        check_secrets(manifest_text)
    except HubError as exc:
        manifest_text = ""
        if manifest_path.exists():
            issues.append(str(exc))
    entries = parse_assets(manifest_text)
    for rel, fields in entries.items():
        if not is_asset_path(prefix + rel):
            issues.append(f"unsafe manifest path: {rel}")
            continue
        path = root / prefix / rel
        try:
            require_workspace_path(root, path)
            validate_asset_file(path)
        except HubError as exc:
            issues.append(str(exc))
            continue
        digest = sha256_file(path)
        if fields.get("SHA-256") != digest:
            issues.append(f"hash mismatch for {rel}; manifest and file disagree.")
        if fields.get("Bytes") != str(path.stat().st_size):
            issues.append(f"byte count mismatch for {rel}.")
        expected_type = "image/" + path.suffix.lower().lstrip(".")
        if fields.get("Type") != expected_type:
            issues.append(f"media type mismatch for {rel}.")
        for key in ("Origin", "Approved by", "Added (UTC)"):
            if not fields.get(key, "").strip():
                issues.append(f"{rel} is missing the '{key}' field.")
    registered = set(entries)
    for rel in local_files(root, prefix):
        rest = rel[len(prefix):]
        if rest.startswith("assets/") and rest not in registered:
            issues.append(f"{rest} is present but not registered in ASSETS.md.")
    return issues


def task_add_asset(root: Path, slug: str, task_id: str, source: Path, *, origin: str,
                   approved_by: str) -> Path:
    """Serialize asset bytes and manifest updates so neither can be lost."""
    git_ready(root)
    with sync_lock(root):
        return _task_add_asset(root, slug, task_id, source, origin=origin,
                               approved_by=approved_by)


def _task_add_asset(root: Path, slug: str, task_id: str, source: Path, *, origin: str,
                    approved_by: str) -> Path:
    """Register one intentionally approved image with a verifiable content hash."""
    folder = task_root(root, slug, task_id)
    require_workspace_path(root, folder)
    require_workspace_path(root, folder / "assets")
    manifest_path = folder / "ASSETS.md"
    if not manifest_path.is_file():
        fail(f"Task packet not found: {task_rel(slug, task_id)}")
    origin = one_line(origin, "--origin")
    approved_by = one_line(approved_by, "--approved-by")
    if (folder / APPROVAL_FILE).exists():
        fail("Assets cannot be added after task approval; create a new task id or revision.")
    source = Path(source).expanduser()
    validate_asset_file(source)
    name = source.name.lower()
    if not ASSET_NAME.fullmatch(name):
        fail(f"Asset name must be lowercase with a png/jpeg/gif/webp extension: {source.name}")
    destination = folder / "assets" / name
    digest = sha256_file(source)
    manifest = read_safe(manifest_path)
    entries = parse_assets(manifest)
    key = f"assets/{name}"
    if key in entries:
        if entries[key].get("SHA-256") != digest:
            fail(f"{key} is already registered with a different hash; never overwrite an "
                 "approved asset. Register the new file under a new name.")
        print(f"{key} already registered with the same hash; nothing to do.")
        return destination
    if destination.exists():
        fail(f"{destination} exists but is not registered; inspect the packet manually.")
    block = (f"\n## {key}\n"
             f"- SHA-256: {digest}\n"
             f"- Bytes: {source.stat().st_size}\n"
             f"- Type: image/{Path(name).suffix.lstrip('.')}\n"
             f"- Origin: {origin}\n"
             f"- Approved by: {approved_by}\n"
             f"- Added (UTC): {stamp()}\n")
    check_secrets(block)
    destination.write_bytes(source.read_bytes())
    manifest_path.write_text(manifest.rstrip("\n") + "\n" + block, encoding="utf-8")
    print(f"Registered {key} ({digest[:12]}…, {source.stat().st_size} bytes)")
    return destination


def packet_issues(root: Path, slug: str, task_id: str, require_approved: bool = True) -> list[str]:
    """Integrity findings for one packet.

    ``require_approved`` separates "is this packet publishable" (publication) from
    "is this packet internally consistent" (validation of a draft-in-progress).
    """
    folder = task_root(root, slug, task_id)
    issues: list[str] = []
    try:
        require_workspace_path(root, folder)
    except HubError as exc:
        return [str(exc)]
    if not folder.is_dir():
        return [f"Task packet missing: {task_rel(slug, task_id)}"]
    contents: dict[str, str] = {}
    for name in TASK_FILES:
        try:
            contents[name] = read_safe(folder / name)
            check_secrets(contents[name])
        except HubError as exc:
            issues.append(f"{name}: {exc}")
    try:
        brief = read_safe(folder / "BRIEF.md")
    except HubError:
        return issues
    for marker in BRIEF_MARKERS:
        if marker not in brief:
            issues.append(f"BRIEF.md: missing {marker}")
    if "- Approval: PENDING" in brief and require_approved:
        issues.append("BRIEF.md: approval is still PENDING; publishing is not allowed.")
    approval_path = folder / APPROVAL_FILE
    if not approval_path.is_file():
        if require_approved:
            issues.append(f"{APPROVAL_FILE}: missing; publication requires a human approval record.")
    else:
        try:
            approval = read_safe(approval_path)
        except HubError as exc:
            issues.append(f"{APPROVAL_FILE}: {exc}")
            approval = ""
        hashes = {
            "- BRIEF.md SHA-256:": brief,
            "- ACCEPTANCE.md SHA-256:": contents.get("ACCEPTANCE.md", ""),
            "- ASSETS.md SHA-256:": contents.get("ASSETS.md", ""),
        }
        for marker in ("- Approved by:", "- Approved (UTC):", "- Approval statement:",
                       *hashes):
            if marker not in approval:
                issues.append(f"{APPROVAL_FILE}: missing {marker}")
        recorded_fields = parse_fields(approval, tuple(hashes))
        for marker, content in hashes.items():
            recorded = recorded_fields.get(marker, "")
            filename = marker.removeprefix("- ").removesuffix(" SHA-256:")
            if not SHA256.fullmatch(recorded):
                issues.append(f"{APPROVAL_FILE}: invalid or missing hash for {filename}")
            elif recorded != sha256_text(content):
                if filename == "BRIEF.md":
                    issues.append("BRIEF.md changed after approval; the approval record no longer "
                                  "binds the brief (create a NEW task id or revision).")
                else:
                    issues.append(f"{filename} changed after approval; the approval record no "
                                  "longer binds the packet (create a NEW task id or revision).")
    prefix = task_rel(slug, task_id)
    issues.extend("ASSETS.md: " + issue for issue in
                  asset_manifest_issues(root, prefix, folder / "ASSETS.md"))
    acceptance = contents.get("ACCEPTANCE.md", "")
    if "- [ ]" not in acceptance and "- [x]" not in acceptance:
        issues.append("ACCEPTANCE.md: no verifiable acceptance criteria found")
    return issues


def verify_packet(root: Path, slug: str, task_id: str) -> None:
    issues = packet_issues(root, slug, task_id, require_approved=True)
    if issues:
        for issue in issues:
            print("FAIL:", issue, file=sys.stderr)
        fail("Task packet is not publishable; no changes were pushed. " + "; ".join(issues[:3]))


def task_publish(root: Path, slug: str, task_id: str) -> None:
    """Publish an approved, verified packet. Never force-pushes and never overwrites."""
    git_ready(root)
    with sync_lock(root):
        verify_packet(root, slug, task_id)
        prefix = task_rel(slug, task_id)
        branch = git_ready(root)
        run_git(root, "fetch", "origin", branch)
        state = remote_state(root, prefix)
        if state == "identical":
            print(f"Task {task_id} is already published at origin/{branch}; no new commit.")
            return
        if state == "different":
            fail(f"An approved task packet already exists on origin/{branch} with different "
                 f"content. Refusing to overwrite it; create a NEW task id or revision.")
        require_git_identity(root)
        publish_paths(root, prefix=prefix, allowed=lambda path: is_task_file(path, prefix),
                      region="task packet",
                      message=lambda count: f"task({slug}/{task_id}): publish approved packet "
                                            f"({count} file(s))")


def task_read(root: Path, slug: str, task_id: str, *, do_sync: bool) -> str:
    if do_sync:
        pull(root)
    folder = task_root(root, slug, task_id)
    require_workspace_path(root, folder)
    if not folder.is_dir():
        fail(f"Task packet not found: {task_rel(slug, task_id)}")
    prefix = task_rel(slug, task_id)
    blocks = [f"# Task packet {task_id}", f"Task path: {prefix}"]
    if (root / ".git").exists():
        rev = run_git(root, "rev-parse", "HEAD", check=False)
        if rev.returncode == 0:
            blocks.append("Git HEAD: " + rev.stdout.strip())
    for name in TASK_FILES:
        try:
            blocks.append(f"\n--- {name} ---\n" + read_safe(folder / name))
        except HubError as exc:
            blocks.append(f"\n--- {name} ---\nUNREADABLE: {exc}")
    if (folder / APPROVAL_FILE).is_file():
        blocks.append(f"\n--- {APPROVAL_FILE} ---\n" + read_safe(folder / APPROVAL_FILE))
    else:
        blocks.append(f"\n--- {APPROVAL_FILE} ---\nNot approved. Publication is not allowed.")
    issues = packet_issues(root, slug, task_id, require_approved=False)
    blocks.append("\n--- packet verification ---\n" +
                  ("PASS: manifest, approval binding and secrets all verified."
                   if not issues else "\n".join("FAIL: " + issue for issue in issues)))
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# UAT feedback records (P1)
# ---------------------------------------------------------------------------

def uat_root(root: Path, slug: str) -> Path:
    return project_path(root, slug) / "uat"


def uat_rel(slug: str, feedback_id: str) -> str:
    return f"projects/{check_slug(slug, 'project')}/uat/{check_uat_id(feedback_id)}/"


def is_uat_file(rel: str, prefix: str) -> bool:
    if not safe_rel(rel) or not rel.startswith(prefix):
        return False
    rest = rel[len(prefix):]
    return rest in UAT_FILES or is_asset_path(rel)


def uat_new(root: Path, slug: str, *, task_id: str, reporter: str, source_repo: str,
            tested_commit: str, environment: str, steps: str, expected: str, observed: str,
            impact: str, severity: str, logs: str, related_pr: str, related_handoff: str,
            screenshot: Path | None, screenshot_origin: str) -> Path:
    if not (project_path(root, slug) / "handoffs").is_dir():
        fail("Project is not initialized.")
    check_slug(reporter, "reporter")
    check_slug(task_id, "task id")
    if severity not in UAT_SEVERITY:
        fail(f"--severity must be one of: {', '.join(UAT_SEVERITY)}")
    for name, value in (("--source-repo", source_repo), ("--tested-commit", tested_commit),
                        ("--environment", environment), ("--steps", steps),
                        ("--expected", expected), ("--observed", observed)):
        if not value.strip():
            fail(f"{name} is required: a usable defect report needs it.")
    source_repo = one_line(source_repo, "--source-repo")
    tested_commit = one_line(tested_commit, "--tested-commit")
    environment = one_line(environment, "--environment")
    if related_pr.strip():
        related_pr = one_line(related_pr, "--related-pr")
    if related_handoff.strip():
        related_handoff = one_line(related_handoff, "--related-handoff")
    if screenshot_origin.strip():
        screenshot_origin = one_line(screenshot_origin, "--screenshot-origin")
    feedback_id = f"{now_utc().strftime('%Y%m%dT%H%M%S%fZ')}_{reporter}_{uuid.uuid4().hex[:10]}"
    folder = uat_root(root, slug) / feedback_id
    require_workspace_path(root, folder)
    if folder.exists():
        fail(f"Feedback id collision: {folder}")
    folder.mkdir(parents=True)
    (folder / "assets").mkdir()
    screenshot_field = "None"
    if screenshot is not None:
        source = Path(screenshot).expanduser()
        validate_asset_file(source)
        name = source.name.lower()
        if not ASSET_NAME.fullmatch(name):
            fail(f"Screenshot name must be lowercase png/jpeg/gif/webp: {source.name}")
        (folder / "assets" / name).write_bytes(source.read_bytes())
        digest = sha256_file(folder / "assets" / name)
        origin = screenshot_origin.strip() or "reporter-provided"
        screenshot_field = f"assets/{name} (SHA-256: {digest}; origin: {origin})"
        manifest = (f"# Approved assets — UAT {feedback_id}\n\n"
                    f"## assets/{name}\n- SHA-256: {digest}\n- Bytes: {source.stat().st_size}\n"
                    f"- Type: image/{Path(name).suffix.lstrip('.')}\n- Origin: {origin}\n"
                    f"- Approved by: {reporter}\n- Added (UTC): {stamp()}\n")
        check_secrets(manifest)
        (folder / "ASSETS.md").write_text(manifest, encoding="utf-8")
    reported = stamp()
    body = (
        f"# UAT feedback {feedback_id}\n\n"
        f"- Project: {slug}\n"
        f"- Feedback ID: {feedback_id}\n"
        f"- Task: {task_id}\n"
        f"- Reporter: {reporter}\n"
        f"- Reported (UTC): {reported}\n"
        f"- Severity: {severity}\n"
        f"- Source repo: {source_repo.strip()}\n"
        f"- Tested commit / build: {tested_commit.strip()}\n"
        f"- Runtime environment: {environment.strip()}\n"
        f"- Screenshot: {screenshot_field}\n"
        f"- Related PR: {related_pr.strip() or 'NOT_OPENED'}\n"
        f"- Related handoff: {related_handoff.strip() or 'NOT_LINKED'}\n\n"
        f"## Reproducible steps\n{steps.strip()}\n\n"
        f"## Expected result\n{expected.strip()}\n\n"
        f"## Observed result\n{observed.strip()}\n\n"
        f"## Impact\n{impact.strip() or 'Not assessed.'}\n\n"
        f"## Logs / references\n{logs.strip() or 'None.'}\n\n"
        f"## Status history (append-only — never rewrite earlier entries)\n"
        f"- {reported} | reported | {reporter} | initial report\n"
    )
    check_secrets(body)
    (folder / "UAT_FEEDBACK.md").write_text(body, encoding="utf-8")
    print(f"Created UAT feedback {uat_rel(slug, feedback_id)} (status: reported)")
    return folder


def uat_history(text: str) -> list[str]:
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## Status history"):
            inside = True
            continue
        if inside and line.startswith("## "):
            inside = False
        if inside and line.startswith("- "):
            lines.append(line[2:].strip())
    return lines


def valid_uat_history_entry(entry: str) -> bool:
    parts = entry.split(" | ", 3)
    if len(parts) != 4 or parts[1] not in UAT_STATUS or not SLUG.fullmatch(parts[2]):
        return False
    try:
        moment = dt.datetime.fromisoformat(parts[0])
    except ValueError:
        return False
    if moment.tzinfo is None or moment.utcoffset() != dt.timedelta(0):
        return False
    return bool(parts[3].strip()) and "\n" not in parts[3] and "\r" not in parts[3]


def uat_current_status(text: str) -> str:
    history = uat_history(text)
    if not history:
        return "unknown"
    parts = [part.strip() for part in history[-1].split("|")]
    return parts[1] if len(parts) > 1 else "unknown"


def uat_issues(root: Path, slug: str, feedback_id: str) -> list[str]:
    check_uat_id(feedback_id)
    folder = uat_root(root, slug) / feedback_id
    require_workspace_path(root, folder)
    issues: list[str] = []
    try:
        text = read_safe(folder / "UAT_FEEDBACK.md")
        check_secrets(text)
    except HubError as exc:
        return [str(exc)]
    for marker in UAT_MARKERS:
        if marker not in text:
            issues.append(f"UAT_FEEDBACK.md: missing {marker}")
    history = uat_history(text)
    if not history:
        issues.append("UAT_FEEDBACK.md: status history is empty")
    elif any(not valid_uat_history_entry(entry) for entry in history):
        issues.append("UAT_FEEDBACK.md: invalid status history entry")
    else:
        states = [entry.split(" | ", 3)[1] for entry in history]
        expected = list(UAT_STATUS[:len(states)])
        if states != expected or len(states) > len(UAT_STATUS):
            issues.append("UAT_FEEDBACK.md: status history skips, repeats, or reorders a transition")
        timestamps = [dt.datetime.fromisoformat(entry.split(" | ", 1)[0]) for entry in history]
        if timestamps != sorted(timestamps):
            issues.append("UAT_FEEDBACK.md: status history timestamps are out of order")
    prefix = uat_rel(slug, feedback_id)
    issues.extend("ASSETS.md: " + issue for issue in
                  asset_manifest_issues(root, prefix, folder / "ASSETS.md"))
    screenshot = parse_fields(text, ("- Screenshot:",)).get("- Screenshot:", "")
    if screenshot and screenshot != "None":
        match = re.fullmatch(r"(assets/[a-z0-9][a-z0-9._-]{0,63}\.(?:png|jpe?g|gif|webp)) "
                             r"\(SHA-256: ([0-9a-f]{64}); origin: .+\)", screenshot)
        if not match:
            issues.append("UAT_FEEDBACK.md: invalid screenshot reference")
        else:
            entries = parse_assets(read_safe(folder / "ASSETS.md"))
            if entries.get(match.group(1), {}).get("SHA-256") != match.group(2):
                issues.append("UAT_FEEDBACK.md: screenshot reference does not match ASSETS.md")
    return issues


def verify_uat(root: Path, slug: str, feedback_id: str) -> None:
    issues = uat_issues(root, slug, feedback_id)
    if issues:
        fail("UAT record is not publishable/readable: " + "; ".join(issues[:3]))


def uat_status(root: Path, slug: str, feedback_id: str, *, status: str, by: str,
               note: str, related_pr: str) -> Path:
    """Serialize local status appends with publication to prevent a lost update."""
    git_ready(root)
    with sync_lock(root):
        return _uat_status(root, slug, feedback_id, status=status, by=by, note=note,
                           related_pr=related_pr)


def _uat_status(root: Path, slug: str, feedback_id: str, *, status: str, by: str,
                note: str, related_pr: str) -> Path:
    """Append a status transition. Earlier lines are never rewritten."""
    if status not in UAT_STATUS:
        fail(f"--status must be one of: {', '.join(UAT_STATUS)}")
    if not by.strip():
        fail("--by is required: every status transition names its author.")
    check_slug(by, "agent")
    check_uat_id(feedback_id)
    note = one_line(note or "no note", "--note")
    if related_pr.strip():
        related_pr = one_line(related_pr, "--related-pr")
    path = uat_root(root, slug) / feedback_id / "UAT_FEEDBACK.md"
    require_workspace_path(root, path)
    text = read_safe(path)
    current = uat_current_status(text)
    if current == status:
        fail(f"Current status is already '{status}'; refusing to append a duplicate entry.")
    next_status = {"reported": "reproduced", "reproduced": "fixed", "fixed": "re-tested"}
    if next_status.get(current) != status:
        fail(f"Invalid UAT transition: '{current}' must move to "
             f"'{next_status.get(current, 'a new feedback record')}', not '{status}'.")
    detail = f"{stamp()} | {status} | {by} | {note}"
    if related_pr.strip():
        detail += f" | PR {related_pr.strip()}"
    check_secrets(detail)
    path.write_text(text.rstrip("\n") + "\n- " + detail + "\n", encoding="utf-8")
    print(f"Appended status '{status}' to {uat_rel(slug, feedback_id)}")
    return path


def uat_publish(root: Path, slug: str, feedback_id: str) -> None:
    """Publish a UAT record. Published history is append-only: rewrites fail closed."""
    git_ready(root)
    with sync_lock(root):
        prefix = uat_rel(slug, feedback_id)
        folder = uat_root(root, slug) / feedback_id
        require_workspace_path(root, folder)
        if not (folder / "UAT_FEEDBACK.md").is_file():
            fail(f"UAT record not found: {prefix}")
        branch = git_ready(root)
        run_git(root, "fetch", "origin", branch)
        state = remote_state(root, prefix)
        if state == "identical":
            print(f"UAT record {feedback_id} is already published at origin/{branch}.")
            return
        if state == "different":
            verify_append_only(root, prefix)
        verify_uat(root, slug, feedback_id)
        require_git_identity(root)
        publish_paths(root, prefix=prefix, allowed=lambda path: is_uat_file(path, prefix),
                      region="UAT record", allow_modified=True,
                      message=lambda count: f"uat({slug}/{feedback_id}): record feedback "
                                            f"({count} file(s))")


def verify_append_only(root: Path, prefix: str) -> None:
    remote = remote_files(root, prefix)
    if not remote:
        return
    local = set(local_files(root, prefix))
    for rel in remote:
        if rel not in local:
            fail(f"Published UAT record is append-only; {rel} was removed or renamed.")
        if is_asset_path(rel):
            if run_git(root, "rev-parse", f"FETCH_HEAD:{rel}").stdout.strip() != \
                    run_git(root, "hash-object", str(root / rel)).stdout.strip():
                fail(f"Published UAT asset must not change: {rel}")
            continue
        old = run_git(root, "cat-file", "blob", f"FETCH_HEAD:{rel}").stdout
        verify_uat_text_append(rel, old, read_safe(root / rel))


def verify_uat_text_append(rel: str, old: str, new: str) -> None:
    if not new.startswith(old):
        fail(f"Published UAT record is append-only; a rewrite was detected in {rel}. "
             "Create a new feedback entry instead of editing history.")
    suffix = new[len(old):]
    if rel.endswith("UAT_FEEDBACK.md"):
        additions = [line[2:] for line in suffix.splitlines() if line]
        if (any(not line.startswith("- ") for line in suffix.splitlines() if line) or
                any(not valid_uat_history_entry(entry) for entry in additions)):
            fail(f"Published UAT record may only append valid status-history lines: {rel}")
    elif rel.endswith("ASSETS.md"):
        old_entries = parse_assets(old)
        new_entries = parse_assets(new)
        if any(new_entries.get(key) != value for key, value in old_entries.items()):
            fail(f"Published UAT asset manifest may only add new entries: {rel}")


def uat_read(root: Path, slug: str, feedback_id: str | None, *, do_sync: bool) -> str:
    if do_sync:
        pull(root)
    base = uat_root(root, slug)
    if feedback_id:
        check_uat_id(feedback_id)
        folder = base / feedback_id
        if not (folder / "UAT_FEEDBACK.md").is_file():
            fail(f"UAT record not found: {uat_rel(slug, feedback_id)}")
        verify_uat(root, slug, feedback_id)
        blocks = [f"# UAT record {feedback_id}",
                  f"Current status: {uat_current_status(read_safe(folder / 'UAT_FEEDBACK.md'))}",
                  read_safe(folder / "UAT_FEEDBACK.md")]
        blocks.append("\n--- status history ---\n" + "\n".join(
            "- " + entry for entry in uat_history(read_safe(folder / "UAT_FEEDBACK.md"))))
        return "\n".join(blocks)
    records = sorted(path for path in base.glob("*/UAT_FEEDBACK.md")) if base.is_dir() else []
    if not records:
        return f"No UAT feedback recorded for {slug}."
    blocks = [f"# UAT feedback for {slug} ({len(records)} record(s))"]
    for path in records:
        text = read_safe(path)
        fields = parse_fields(text, ("- Feedback ID:", "- Task:", "- Severity:",
                                     "- Tested commit / build:"))
        blocks.append(f"\n--- {path.parent.name} ---\n"
                      f"- Status: {uat_current_status(text)}\n"
                      + "\n".join(f"{key} {value}" for key, value in fields.items()))
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Onboarding check (fail closed)
# ---------------------------------------------------------------------------

def remote_reachable(url: str) -> tuple[bool, str]:
    """A real network read against the remote. Failure is reported, never assumed away."""
    result = subprocess.run(["git", "ls-remote", "--heads", url], text=True, encoding="utf-8",
                            errors="surrogateescape", capture_output=True, check=False)
    if result.returncode == 0:
        return True, "ok"
    output = (result.stderr or result.stdout).strip()
    return False, output.splitlines()[0] if output else "unreachable"


def onboard_check(root: Path, *, source_repo: str = "", prove_push: bool = False) -> int:
    """Verify the access an agent needs BEFORE claiming code review can happen.

    Anything unproven is reported as BLOCKED/UNKNOWN rather than assumed to work.
    """
    rows: list[tuple[str, str, str]] = []
    push_ok = False
    identity_ok = False

    try:
        branch = git_ready(root)
    except HubError as exc:
        rows.append(("CONTEXT_REPO", "BLOCKED", str(exc)))
    else:
        rows.append(("CONTEXT_REPO", "PASS", f"Git checkout on branch {branch}"))
        url = run_git(root, "remote", "get-url", "origin", check=False).stdout.strip()
        ok, detail = remote_reachable(url) if url else (False, "no origin remote")
        rows.append(("CONTEXT_READ", "PASS" if ok else "BLOCKED", detail if not ok else url))
        try:
            require_git_identity(root)
            rows.append(("GIT_IDENTITY", "PASS", "committer identity resolves"))
            identity_ok = True
        except HubError as exc:
            rows.append(("GIT_IDENTITY", "BLOCKED", str(exc)))
        if prove_push:
            if identity_ok:
                ok, detail = probe_push(root, branch)
                rows.append(("CONTEXT_PUSH", "PASS" if ok else "BLOCKED", detail))
                push_ok = ok
            else:
                rows.append(("CONTEXT_PUSH", "BLOCKED",
                             "live proof requires a valid Git committer identity"))
        else:
            rows.append(("CONTEXT_PUSH", "UNKNOWN",
                         "read access and remote history do not prove current write permission; "
                         "rerun with --prove-push for a live proof"))
            push_ok = False

    if source_repo.strip():
        ok, detail = remote_reachable(source_repo.strip())
        rows.append(("SOURCE_READ", "PASS" if ok else "BLOCKED",
                     source_repo.strip() if ok else f"{source_repo.strip()}: {detail}"))
        source_ok = ok
    else:
        rows.append(("SOURCE_READ", "NOT_PROVIDED",
                     "no --source-repo given; code review from another tool stays BLOCKED"))
        source_ok = False

    rows.append(("CONNECTOR_READ", "UNKNOWN",
                 "connector/chat read permission cannot be verified by this CLI; "
                 "test it in the connector and record the result in a handoff"))

    print("ONBOARDING CHECK")
    for name, status, detail in rows:
        print(f"  {name:<15} {status:<13} {detail}")
    verdict = "READY" if (push_ok and source_ok and
                          all(r[1] != "BLOCKED" for r in rows if r[0] in
                              ("CONTEXT_REPO", "CONTEXT_READ", "GIT_IDENTITY"))) else "BLOCKED"
    print(f"VERDICT: {verdict}")
    if verdict == "BLOCKED":
        print("Independent code review is BLOCKED until SOURCE_READ and CONTEXT_PUSH are proven. "
              "Resolve the access above instead of asking for another ZIP of the project.")
    return 0 if verdict == "READY" else 1


def probe_push(root: Path, branch: str) -> tuple[bool, str]:
    """Push a throw-away ref to prove write permission, then read it back and delete it."""
    tree = run_git(root, "rev-parse", "HEAD^{tree}").stdout.strip()
    commit = run_git(root, "commit-tree", tree, "-m", "ach onboarding probe").stdout.strip()
    probe = f"refs/ach-onboard/{uuid.uuid4().hex[:12]}"
    pushed = run_git(root, "push", "origin", f"{commit}:{probe}", check=False)
    if pushed.returncode:
        return False, (pushed.stderr or pushed.stdout).strip().splitlines()[-1]
    readback = ""
    read_error = ""
    try:
        readback_result = run_git(root, "ls-remote", "origin", probe, check=False)
        readback = readback_result.stdout.strip()
        if readback_result.returncode:
            read_error = (readback_result.stderr or readback_result.stdout).strip()
    except HubError as exc:
        read_error = str(exc)
    finally:
        cleanup = run_git(root, "push", "origin", "--delete", probe, check=False)
    if read_error:
        return False, "probe readback failed; cleanup attempted: " + read_error
    if commit not in readback:
        return False, "probe ref did not read back; write permission unproven"
    if cleanup.returncode:
        return False, f"probe ref {probe} could not be removed; delete it manually"
    return True, "live push + read-back + cleanup succeeded"


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------

def write_handoff(root: Path, project: str, agent: str, task: str,
                  result: str, evidence: str, risks: str, next_step: str, status: str,
                  *, source_repo: str = "", branch: str = "", code_sha: str = "",
                  pr: str = "", build: str = "", tests: str = "", acceptance: str = "",
                  uat: str = "") -> Path:
    folder = project_path(root, project)
    if not folder.exists() or not (folder / "handoffs").is_dir():
        fail("Project is not initialized.")
    check_slug(agent, "agent")
    if not task.strip() or not result.strip():
        fail("Task and result must be nonempty.")
    if status not in HANDOFF_STATUS:
        fail(f"--status must be one of: {', '.join(HANDOFF_STATUS)}")
    now = now_utc()
    handoff_id = now.strftime("%Y%m%dT%H%M%S%fZ") + f"_{agent}_{uuid.uuid4().hex[:10]}"
    content = (
        f"# Handoff {handoff_id}\n\n"
        f"- Project: {project}\n- Agent: {agent}\n- Timestamp (UTC): {now.isoformat()}\n"
        f"- Status: {status}\n\n## Task\n{task.strip()}\n\n"
        f"## Actions / results\n{result.strip()}\n\n## Evidence\n{evidence.strip() or 'NOT_VERIFIED'}\n\n"
        f"## Risks / uncertainty\n{risks.strip() or 'Not assessed'}\n\n"
        f"## Next step\n{next_step.strip() or 'Await user instruction'}\n"
    )
    implemented = any(value.strip() for value in (source_repo, branch, code_sha, pr, build,
                                                 tests, acceptance, uat))
    if implemented:
        for name, value in (("--source-repo", source_repo), ("--branch", branch),
                            ("--code-sha", code_sha)):
            if not value.strip():
                fail(f"{name} is required when recording an implementation result.")
        if not CODE_SHA.fullmatch(code_sha.strip()):
            fail("--code-sha must be a real 7-40 character hex commit SHA, not a placeholder.")
        if not pr.strip():
            fail("--pr is required when recording an implementation result; pass NOT_OPENED if "
                 "no pull request exists.")
        for name, value in (("--source-repo", source_repo), ("--branch", branch),
                            ("--code-sha", code_sha), ("--pr", pr)):
            one_line(value, name)
        acceptance_value = (acceptance or "PENDING").strip().upper()
        if acceptance_value not in ("PENDING", "PASSED"):
            fail("--acceptance must be PENDING or PASSED.")
        if acceptance_value == "PASSED":
            if not uat.strip():
                fail("--acceptance PASSED requires --uat <feedback-id>; AI implementation done is "
                     "not the same as human UAT passed.")
            feedback_id = check_uat_id(uat.strip())
            verify_uat(root, project, feedback_id)
            record = uat_root(root, project) / feedback_id / "UAT_FEEDBACK.md"
            if not record.is_file():
                fail(f"--uat {uat.strip()} does not exist in this checkout.")
            state = uat_current_status(read_safe(record))
            if state != "re-tested":
                fail(f"UAT feedback {uat.strip()} is '{state}', not 're-tested'; "
                     "human acceptance cannot be declared yet.")
            fields = parse_fields(read_safe(record),
                                  ("- Source repo:", "- Tested commit / build:"))
            if fields.get("- Source repo:") != source_repo.strip():
                fail("The re-tested UAT record belongs to a different source repository.")
            if fields.get("- Tested commit / build:") != code_sha.strip():
                fail("The re-tested UAT record does not match --code-sha.")
        one_line(build, "--build")
        one_line(tests, "--tests")
        content += (
            "\n## Implementation evidence\n"
            f"- Source repo: {source_repo.strip()}\n"
            f"- Branch: {branch.strip()}\n"
            f"- Code SHA: {code_sha.strip()}\n"
            f"- PR: {pr.strip()}\n"
            f"- Build / run instructions: {build.strip() or 'Not provided.'}\n"
            f"- Test evidence: {tests.strip() or 'NOT_VERIFIED'}\n"
            f"- Human acceptance: {acceptance_value}"
            + (f" (UAT feedback {uat.strip()})" if uat.strip() else
               " — AI implementation complete, human UAT outstanding")
            + "\n"
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
    errors: list[str] = []
    files = [folder / f for f in FILES]
    files.extend((folder / "handoffs").glob("*.md"))
    for sub in ("tasks", "uat"):
        if (folder / sub).is_dir():
            files.extend((folder / sub).rglob("*.md"))
    for path in files:
        try:
            content = read_safe(path)
            check_secrets(content)
            if "handoffs" in path.parts and path.name != "README.md":
                for marker in ("- Agent:", "- Status:", "## Task", "## Actions / results", "## Evidence"):
                    if marker not in content:
                        errors.append(f"{path}: missing {marker}")
                if "## Implementation evidence" in content:
                    for marker in HANDOFF_IMPL_MARKERS:
                        if marker not in content:
                            errors.append(f"{path}: implementation evidence missing {marker}")
            elif path.name == "BRIEF.md":
                for marker in BRIEF_MARKERS:
                    if marker not in content:
                        errors.append(f"{path}: missing {marker}")
            elif path.name == "UAT_FEEDBACK.md":
                for marker in UAT_MARKERS:
                    if marker not in content:
                        errors.append(f"{path}: missing {marker}")
                if not uat_history(content):
                    errors.append(f"{path}: status history is empty")
            elif path.name == "ACCEPTANCE.md" and "- [ ]" not in content and "- [x]" not in content:
                errors.append(f"{path}: no verifiable acceptance criteria found")
        except HubError as exc:
            errors.append(str(exc))
    if (folder / "tasks").is_dir():
        for task_dir in sorted(path for path in (folder / "tasks").iterdir() if path.is_dir()):
            try:
                found = packet_issues(root, slug, task_dir.name, require_approved=False)
            except HubError as exc:
                found = [str(exc)]
            errors.extend(f"tasks/{task_dir.name}: {issue}" for issue in found)
    if (folder / "uat").is_dir():
        for uat_dir in sorted(path for path in (folder / "uat").iterdir() if path.is_dir()):
            try:
                found = uat_issues(root, slug, uat_dir.name)
            except HubError as exc:
                found = [str(exc)]
            errors.extend(f"uat/{uat_dir.name}: {issue}" for issue in found)
    if errors:
        for error in errors:
            print("FAIL:", error, file=sys.stderr)
        return 1
    print(f"PASS: {slug}; validated {len(files)} Markdown files")
    return 0


# ---------------------------------------------------------------------------
# Context rendering
# ---------------------------------------------------------------------------

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
    blocks.append("\n--- available packets ---\n" + render_index(root, slug))
    return "\n".join(blocks)


def render_index(root: Path, slug: str) -> str:
    folder = project_path(root, slug)
    task_dirs = sorted(path for path in (folder / "tasks").glob("*") if path.is_dir()) \
        if (folder / "tasks").is_dir() else []
    if task_dirs:
        approvals = []
        for path in task_dirs:
            state = "approved" if (path / APPROVAL_FILE).is_file() else "draft"
            approvals.append(f"{path.name} ({state})")
        lines = ["Task packets: " + ", ".join(approvals)
                 + "  → read with `task-read --project %s --task <id>`" % slug]
    else:
        lines = ["Task packets: none."]
    uat_dirs = sorted(path for path in (folder / "uat").glob("*/UAT_FEEDBACK.md")) \
        if (folder / "uat").is_dir() else []
    if uat_dirs:
        lines.append("UAT feedback: " + ", ".join(
            f"{path.parent.name} [{uat_current_status(read_safe(path))}]" for path in uat_dirs))
    else:
        lines.append("UAT feedback: none.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Application-source repository onboarding (v0.3)
#
# Three layers stay isolated and this section only ever touches the third one:
#   * public tool repository      (this code)
#   * private context repository  (records; unchanged by this section)
#   * private application-source  (onboarded here, one repository per project)
#
# Nothing in this section writes into the inspected project until an explicitly
# approved manifest authorises a first upload. Inspection itself is read-only.
# ---------------------------------------------------------------------------

SOURCE_PLAN_FILE = "SOURCE_PLAN.md"
SOURCE_MANIFEST_FILE = "SOURCE_MANIFEST.txt"
SOURCE_RESULT_FILE = "SOURCE_RESULT.md"
SOURCE_VERIFY_FILE = "SOURCE_VERIFY.md"
SOURCE_ACCESS_FILE = "SOURCE_ACCESS.md"
MAX_SOURCE_FILE = 5_000_000
MAX_SOURCE_TOTAL = 200_000_000
MAX_SOURCE_FILES = 5_000
SOURCE_SCAN_BYTES = 262_144
SOURCE_SCAN_FILES = 2_000
SOURCE_WORK_FILES = (SOURCE_PLAN_FILE, SOURCE_MANIFEST_FILE, SOURCE_RESULT_FILE,
                     SOURCE_VERIFY_FILE, SOURCE_ACCESS_FILE)
SOURCE_TOOL_STATUS = ("verified", "pending", "blocked")
DEFAULT_SOURCE_IGNORE = frozenset((
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".cache", ".gradle",
    "dist", "build", "target", "out", "bin", "obj", ".next", ".nuxt", "coverage",
    "htmlcov", ".idea", ".vscode", ".DS_Store", "vendor", ".terraform",
))
SOURCE_DENY_SUFFIX = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".p8",
                      ".ppk", ".sqlite", ".sqlite3", ".db", ".db-wal", ".db-shm",
                      ".mdb", ".pgpass", ".kdbx")
SOURCE_DENY_NAMES = frozenset((
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa.pub", ".netrc", ".npmrc",
    ".pypirc", ".htpasswd", ".pgpass", "credentials", "credentials.json",
    "secrets.json", "secrets.yaml", "secrets.yml", ".env.local", ".env.production",
    ".env.development", ".env.staging",
))
SOURCE_REVIEW_SUFFIX = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
                        ".bak", ".dump", ".sql", ".iso", ".dmg", ".pkg")
SOURCE_FLAG_WORDS = ("backup", "备份", "password", "credential", "secret",
                     "密钥", "密码", "token")


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:,.1f} TB"


def source_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_dir():
        fail(f"Local project directory not found: {path}")
    return path.resolve()


def require_external_workdir(project: Path, workdir: Path) -> Path:
    """The work directory must exist and must not live inside the inspected project."""
    project = project.expanduser().resolve()
    workdir = workdir.expanduser().resolve()
    if not workdir.is_dir():
        fail(f"Work directory not found: {workdir}. Create it first; this tool will not create it.")
    if workdir == project or project in workdir.parents:
        fail("The work directory must be OUTSIDE the inspected project, so inspection and "
             "planning cannot write into the project.")
    if workdir == Path("/") or workdir == Path.home():
        fail("Refusing to use a system or home directory as the work directory.")
    return workdir


def source_deny_reason(rel: str, path: Path, scan_budget: list[int]) -> str | None:
    """Hard denials: never uploadable and never overridable."""
    name = path.name
    lower = name.lower()
    if lower.startswith(".env") and lower != ".env.example":
        return "environment file (likely contains credentials)"
    if lower in SOURCE_DENY_NAMES:
        return "credential/key file name"
    if path.suffix.lower() in SOURCE_DENY_SUFFIX:
        return f"credential, key or database file type ({path.suffix.lower()})"
    try:
        size = path.stat().st_size
    except OSError:
        return "unreadable file"
    if size <= SOURCE_SCAN_BYTES and scan_budget[0] > 0:
        scan_budget[0] -= 1
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None
        if secret_hit(text):
            return "credential pattern detected inside the file"
    return None


def source_review_reason(rel: str, path: Path, size: int) -> str | None:
    """Excluded unless the owner explicitly promotes them with --allow-review."""
    if path.suffix.lower() in SOURCE_REVIEW_SUFFIX:
        return f"archive/backup/dump file type ({path.suffix.lower()})"
    if size >= MAX_SOURCE_FILE:
        return f"larger than the per-file limit ({human_bytes(size)})"
    return None


def source_flags(rel: str) -> list[str]:
    lower = rel.lower()
    return [word for word in SOURCE_FLAG_WORDS if word in lower]


def walk_project(project: Path) -> list[tuple[str, Path, int]]:
    found: list[tuple[str, Path, int]] = []
    for base, dirs, files in os.walk(project):
        dirs[:] = [name for name in dirs
                   if name not in DEFAULT_SOURCE_IGNORE and not (Path(base) / name).is_symlink()]
        for name in files:
            path = Path(base) / name
            if path.is_symlink():
                continue
            try:
                found.append((path.relative_to(project).as_posix(), path, path.stat().st_size))
            except OSError:
                continue
    return sorted(found)


def select_source_files(project: Path, includes: tuple[str, ...]) -> tuple[list, dict]:
    """Determine the candidate set. Tracked files only when the project is a Git repo."""
    notes: list[str] = []
    candidates: dict[str, tuple[Path, int]] = {}
    if (project / ".git").is_dir():
        tracked = [item for item in run_git(project, "ls-files", "-z").stdout.split("\0") if item]
        notes.append("selection = files already tracked by the project's own Git; the project's "
                     ".gitignore was therefore already reviewed and is respected")
        for rel in tracked:
            if not safe_rel(rel):
                continue
            path = project / rel
            if path.is_symlink() or not path.is_file():
                continue
            try:
                candidates[rel] = (path, path.stat().st_size)
            except OSError:
                continue
    else:
        notes.append("project is NOT a Git repository; selection falls back to a working-tree walk "
                     "that skips VCS, virtualenv, cache, dependency and build-output directories")
        for rel, path, size in walk_project(project):
            candidates[rel] = (path, size)

    added: list[str] = []
    for pattern in includes:
        if not pattern.strip():
            continue
        matches = [Path(item) for item in glob.glob(str(project / pattern), recursive=True)]
        if not matches:
            fail(f"--include matched nothing: {pattern}")
        for match in matches:
            resolved = match.resolve()
            if resolved == project or project not in resolved.parents:
                fail(f"--include escapes the project: {pattern}")
            if resolved.is_symlink():
                fail(f"--include points at a symlink: {pattern}")
            targets = walk_project(resolved) if resolved.is_dir() else [
                (resolved.relative_to(project).as_posix(), resolved, resolved.stat().st_size)]
            for rel, path, size in targets:
                if rel not in candidates:
                    added.append(rel)
                candidates[rel] = (path, size)
    if added:
        notes.append(f"--include added {len(added)} path(s) that Git does not track: "
                     + ", ".join(sorted(added)[:10]))

    untracked = []
    if (project / ".git").is_dir():
        untracked = [rel for rel in run_git(project, "ls-files", "--others",
                                            "--exclude-standard", "-z").stdout.split("\0")
                     if rel and rel not in candidates]
        if untracked:
            notes.append(f"{len(untracked)} file(s) are untracked and NOT in the manifest (add them "
                         "with --include if they belong in the repository): "
                         + ", ".join(sorted(untracked)[:10]))

    decided: list = []
    hard: list[tuple[str, str]] = []
    review: list[tuple[str, str, int]] = []
    flagged: list[tuple[str, list[str]]] = []
    scan_budget = [SOURCE_SCAN_FILES]
    for rel in sorted(candidates):
        path, size = candidates[rel]
        reason = source_deny_reason(rel, path, scan_budget)
        if reason:
            hard.append((rel, reason))
            continue
        review_reason = source_review_reason(rel, path, size)
        if review_reason:
            review.append((rel, review_reason, size))
            continue
        flagged_words = source_flags(rel)
        if flagged_words:
            flagged.append((rel, flagged_words))
        decided.append((rel, path, size))
    return decided, {"notes": notes, "hard": hard, "review": review, "flagged": flagged,
                     "candidates": candidates}


def source_history_findings(project: Path) -> list[tuple[str, str]]:
    """Any denied path that ever entered the project's Git history would be uploaded too."""
    if not (project / ".git").is_dir():
        return []
    listing = run_git(project, "log", "--all", "--pretty=format:", "--name-only",
                      "-z", check=False)
    if listing.returncode:
        return []
    seen: dict[str, str] = {}
    scan_budget = [SOURCE_SCAN_FILES]
    for rel in {item for item in listing.stdout.split("\0") if item}:
        if not safe_rel(rel) or rel in seen:
            continue
        path = project / rel
        if path.is_file():
            reason = source_deny_reason(rel, path, scan_budget)
        else:
            reason = None
            name = Path(rel).name.lower()
            if (name.startswith(".env") and name != ".env.example") or name in SOURCE_DENY_NAMES \
                    or Path(rel).suffix.lower() in SOURCE_DENY_SUFFIX:
                reason = "denied file type present in Git history"
        if reason:
            seen[rel] = reason
    return sorted(seen.items())


def ignored_dir_summary(project: Path) -> list[tuple[str, int, int]]:
    summary = []
    for base, dirs, _files in os.walk(project):
        for name in list(dirs):
            if name == ".git":
                dirs.remove(name)
                continue
            if name in DEFAULT_SOURCE_IGNORE:
                path = Path(base) / name
                total = 0
                count = 0
                for walk_base, _dirs, files in os.walk(path):
                    for filename in files:
                        try:
                            total += (Path(walk_base) / filename).stat().st_size
                            count += 1
                        except OSError:
                            continue
                summary.append((path.relative_to(project).as_posix(), count, total))
                dirs.remove(name)
    return sorted(summary, key=lambda item: -item[2])[:10]


def render_source_inspect(project: Path, selection) -> str:
    decided, info = selection
    total = sum(size for _rel, _path, size in decided)
    lines = ["SOURCE PROJECT INSPECTION (read-only)", "=" * 60,
             f"project path         : {project}",
             f"is git repository    : {(project / '.git').is_dir()}"]
    if (project / ".git").is_dir():
        branch = run_git(project, "branch", "--show-current", check=False).stdout.strip()
        head = run_git(project, "rev-parse", "HEAD", check=False).stdout.strip()
        remotes = [line for line in run_git(project, "remote", "-v", check=False)
                   .stdout.splitlines()]
        lines += [f"current branch       : {branch or '(detached or unborn)'}",
                  f"HEAD sha             : {head or '(no commits)'}",
                  f"commit count         : {run_git(project, 'rev-list', '--count', 'HEAD', check=False).stdout.strip() or 0}",
                  f"remotes              : {remotes if remotes else 'NONE — nothing has been pushed yet'}"]
        status = [line for line in run_git(project, "status", "--porcelain", check=False)
                  .stdout.splitlines() if line]
        lines.append(f"uncommitted entries  : {len(status)}")
        for entry in status[:8]:
            lines.append(f"    {entry}")
    lines += ["", "--- upload selection ---",
              f"candidate files      : {len(decided)}",
              f"candidate bytes      : {human_bytes(total)}"]
    for note in info["notes"]:
        lines.append(f"    note: {note}")
    lines.append("")
    lines.append(f"HARD-DENIED in selection : {len(info['hard'])}")
    lines += [f"    DENY  {rel}  ({reason})" for rel, reason in info["hard"][:25]] or ["    (none)"]
    lines.append("")
    lines.append(f"REQUIRES EXPLICIT REVIEW : {len(info['review'])}")
    for rel, reason, size in info["review"][:25]:
        lines.append(f"    REVIEW  {human_bytes(size):>10}  {rel}  ({reason})")
    if not info["review"]:
        lines.append("    (none)")
    lines.append("")
    lines.append(f"FLAGGED NAMES (informational only, still included) : {len(info['flagged'])}")
    lines += [f"    FLAG  {rel}  ({', '.join(words)})" for rel, words in info["flagged"][:15]]
    if not info["flagged"]:
        lines.append("    (none)")
    lines.append("")
    lines.append("HARD-DENIED IN GIT HISTORY :")
    history = source_history_findings(project)
    lines += [f"    DENY  {rel}  ({reason})" for rel, reason in history[:25]] or ["    (none)"]
    lines.append("")
    lines.append("IGNORED DIRECTORIES PRESENT (not uploaded, listed for awareness):")
    ignored = ignored_dir_summary(project)
    lines += [f"    {human_bytes(size):>10}  {count:>5} files  {rel}/" for rel, count, size in ignored]
    if not ignored:
        lines.append("    (none)")
    lines.append("")
    verdict = "BLOCKED: hard-denied files are present — resolve them before planning" \
        if info["hard"] or history else "READY for source-plan"
    lines += ["-" * 60, f"VERDICT: {verdict}",
              "Nothing was written, moved, staged or deleted by this inspection."]
    return "\n".join(lines)


def source_inspect(project: Path, includes: tuple[str, ...] = (),
                   manifest_out: Path | None = None) -> str:
    selection = select_source_files(project, includes)
    report = render_source_inspect(project, selection)
    if manifest_out is not None:
        target = manifest_out.expanduser()
        if target.exists():
            fail(f"Refusing to overwrite the existing manifest: {target}")
        body, digest = build_manifest(project, selection[0])
        target.write_text(
            "# AI Context Hub candidate manifest (review copy, not yet approved)\n"
            f"# project    : {project}\n# digest     : {digest}\n"
            "# one line per file: <sha256>  <bytes>  <relative path>\n" + body,
            encoding="utf-8")
        report += (f"\n\nCANDIDATE MANIFEST WRITTEN: {target}\n"
                   f"CANDIDATE DIGEST: {digest}\n"
                   "This is a review copy only: it is not an approved manifest, nothing was "
                   "staged, and no destination was contacted.")
    return report


def github_slug(url: str) -> str | None:
    match = re.match(r"^(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?/?$",
                     url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def destination_is_local(url: str) -> bool:
    value = url.strip()
    if value.startswith("file://"):
        return True
    return not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://|^[^/]+@[^/]+:", value)


def default_api_probe(slug: str) -> int:
    """Unauthenticated GitHub API status for a repository: 200 public, 404 not public."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ai-context-hub"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:
        return 0


def check_destination(url: str, api_probe=None, remote_probe=None) -> tuple[str, str]:
    """Return (kind, detail) where kind is local | private | refused."""
    value = url.strip()
    if not value or "\n" in value:
        fail("--dest must be one non-empty line.")
    if destination_is_local(value):
        path = Path(value.removeprefix("file://")).expanduser()
        if not path.exists():
            return "refused", (f"local destination does not exist: {path}. Create the bare repository "
                               "first (for example: git init --bare <path>).")
        return "local", f"local/filesystem destination (no network visibility applies): {path}"
    slug = github_slug(value)
    if slug is None:
        return "refused", (f"cannot verify visibility of {value}: only github.com destinations can be "
                           "checked for public exposure by this tool. Create the repository with "
                           "private visibility and pass its github.com URL.")
    probe = api_probe or default_api_probe
    status = probe(slug)
    if status == 200:
        return "refused", (f"{slug} is readable without authentication, so it is PUBLIC. Refusing: "
                           "application source must live in a private repository.")
    reachable = remote_probe(value) if remote_probe else git_remote_reachable(value)
    if not reachable[0]:
        return "refused", (f"{slug} is not publicly readable (good) but Git access also failed, so it "
                           "does not exist yet or this machine lacks credentials. Create the PRIVATE "
                           "repository and grant this machine access, then rerun. "
                           f"git said: {reachable[1]}")
    return "private", f"{slug}: not publicly readable via the API and readable via Git — verified private"


def git_remote_reachable(url: str) -> tuple[bool, str]:
    result = subprocess.run(["git", "ls-remote", url], text=True, encoding="utf-8",
                            errors="surrogateescape", capture_output=True, check=False)
    if result.returncode == 0:
        return True, "ok"
    output = (result.stderr or result.stdout).strip()
    return False, output.splitlines()[0] if output else "no output"


def manifest_body(entries: list[tuple[str, int, str]]) -> str:
    return "\n".join(f"{digest}  {size}  {rel}" for rel, size, digest in entries) + "\n"


def build_manifest(project: Path, decided) -> tuple[str, str]:
    entries = []
    for rel, path, size in decided:
        entries.append((rel, size, sha256_file(path)))
    body = manifest_body(entries)
    return body, sha256_text(body)


def source_plan(project: Path, slug: str, dest: str, workdir: Path, *, authorize: str,
                statement: str, includes: tuple[str, ...], allow_review: tuple[str, ...],
                branch: str = "", api_probe=None, remote_probe=None) -> tuple[Path, str]:
    project = project.expanduser().resolve()
    slug = check_slug(slug, "project slug")
    authorize = one_line(authorize, "--authorize")
    statement = one_line(statement, "--statement")
    workdir = require_external_workdir(project, workdir)
    if (workdir / SOURCE_PLAN_FILE).exists():
        fail(f"{SOURCE_PLAN_FILE} already exists in the work directory. Use a fresh directory for a "
             "new plan, or run source-publish on the existing one.")
    if not branch.strip():
        branch = run_git(project, "branch", "--show-current", check=False).stdout.strip() \
            if (project / ".git").is_dir() else ""
        branch = branch or "main"
    branch = one_line(branch, "--branch")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,120}", branch):
        fail(f"Unsafe branch name: {branch}")
    kind, detail = check_destination(dest, api_probe, remote_probe)
    if kind == "refused":
        fail(f"Destination not usable: {detail}")

    decided, info = select_source_files(project, includes)
    history = source_history_findings(project)
    if info["hard"]:
        listing = "; ".join(f"{rel} ({reason})" for rel, reason in info["hard"][:5])
        fail(f"Refusing to plan: {len(info['hard'])} hard-denied file(s) are selected for upload. "
             f"Remove or ignore them first: {listing}")
    if history:
        listing = "; ".join(f"{rel} ({reason})" for rel, reason in history[:5])
        fail(f"Refusing to plan: {len(history)} hard-denied path(s) exist in this project's Git "
             "history, so pushing that history would upload them too. This tool never rewrites "
             f"history: {listing}")

    promoted, remaining = [], []
    for rel, reason, size in info["review"]:
        if any(fnmatch.fnmatch(rel, pattern) for pattern in allow_review):
            promoted.append((rel, reason, size))
        else:
            remaining.append((rel, reason, size))
    entries = [(rel, path, size) for rel, path, size in decided]
    for rel, reason, size in promoted:
        entries.append((rel, project / rel, size))
    entries.sort(key=lambda item: item[0])
    total = sum(size for _rel, _path, size in entries)
    if len(entries) > MAX_SOURCE_FILES:
        fail(f"Refusing to plan: {len(entries)} files exceeds the {MAX_SOURCE_FILES} file ceiling.")
    if total > MAX_SOURCE_TOTAL:
        fail(f"Refusing to plan: {human_bytes(total)} exceeds the {human_bytes(MAX_SOURCE_TOTAL)} "
             "ceiling. Narrow the selection.")
    if not entries:
        fail("Refusing to plan: no files were selected for upload.")

    body, digest = build_manifest(project, entries)
    (workdir / SOURCE_MANIFEST_FILE).write_text(
        "# AI Context Hub source manifest\n"
        f"# project    : {slug}\n# local path : {project}\n# destination: {dest.strip()}\n"
        f"# branch     : {branch}\n# digest     : {digest}\n"
        "# one line per file: <sha256>  <bytes>  <relative path>\n" + body, encoding="utf-8")

    init_note = "the project is not a Git repository, so the approved first upload will run " \
                f"`git init -b {branch}` inside it (nothing is deleted or rewritten)" \
        if not (project / ".git").is_dir() else \
        f"the existing Git repository and its history are reused; no git init, no remote rewrite"
    plan = (
        f"# Source onboarding plan — {slug}\n\n"
        f"- Project slug: {slug}\n- Local project path: {project}\n- Destination: {dest.strip()}\n"
        f"- Destination check: {detail}\n- Branch: {branch}\n- Planned (UTC): {stamp()}\n"
        f"- Authorized by: {authorize}\n- Authorization statement: {statement}\n"
        f"- Files approved: {len(entries)}\n- Total bytes: {total} ({human_bytes(total)})\n"
        f"- Manifest SHA-256: {digest}\n"
        f"- Git handling: {init_note}\n\n"
        "## Hard rules applied to this selection\n\n"
        "- Environment files, key material, databases and credential patterns are refused, not "
        "merely excluded, and cannot be overridden.\n"
        "- Any denied path present anywhere in the project's Git history refuses the whole plan, "
        "because pushing the history would publish it.\n"
        "- Archive, dump, backup and oversized files are excluded unless explicitly promoted with "
        "`--allow-review`.\n"
        "- Nothing is staged or pushed by planning; the working tree is not modified.\n\n"
        "## Notes\n\n" + "\n".join(f"- {note}" for note in info["notes"]) + "\n\n"
        "## Excluded for explicit review (not uploaded)\n\n"
        + ("\n".join(f"- `{rel}` — {reason} ({human_bytes(size)})"
                     for rel, reason, size in remaining) or "- none") + "\n\n"
        "## Promoted past review by explicit authorization\n\n"
        + ("\n".join(f"- `{rel}` — {reason} ({human_bytes(size)})"
                     for rel, reason, size in sorted(promoted)) or "- none") + "\n\n"
        "## Next step\n\n"
        f"`source-publish --workdir {workdir} --approve-manifest {digest}`\n\n"
        "Approving the digest means you have reviewed the exact file list in "
        f"{SOURCE_MANIFEST_FILE}.\n")
    check_secrets(plan)
    path = workdir / SOURCE_PLAN_FILE
    with path.open("x", encoding="utf-8") as handle:
        handle.write(plan)
    print(render_source_inspect(project, (decided, info)))
    print()
    print(f"PLAN WRITTEN: {path}")
    print(f"MANIFEST    : {workdir / SOURCE_MANIFEST_FILE} ({len(entries)} files, "
          f"{human_bytes(total)})")
    print(f"DESTINATION : {kind} — {detail}")
    print(f"APPROVE WITH: --approve-manifest {digest}")
    print("Nothing was staged, committed or pushed.")
    return path, digest


def read_plan(workdir: Path) -> dict:
    workdir = workdir.expanduser().resolve()
    plan_path = workdir / SOURCE_PLAN_FILE
    manifest_path = workdir / SOURCE_MANIFEST_FILE
    if not plan_path.is_file() or not manifest_path.is_file():
        fail(f"No source onboarding plan found in {workdir} (expected {SOURCE_PLAN_FILE} and "
             f"{SOURCE_MANIFEST_FILE}). Run source-plan first.")
    plan = read_safe(plan_path)
    fields = parse_fields(plan, ("- Project slug:", "- Local project path:", "- Destination:",
                                 "- Branch:", "- Manifest SHA-256:", "- Authorized by:"))
    for key in ("- Project slug:", "- Local project path:", "- Destination:", "- Branch:",
                "- Manifest SHA-256:"):
        if not fields.get(key):
            fail(f"{SOURCE_PLAN_FILE} is missing {key}")
    manifest_text = read_safe(manifest_path)
    body = "".join(line + "\n" for line in manifest_text.splitlines()
                   if line and not line.startswith("#"))
    entries = []
    for line in body.splitlines():
        parts = line.split("  ")
        if len(parts) != 3:
            fail(f"{SOURCE_MANIFEST_FILE} has a malformed line: {line}")
        digest, size, rel = parts
        entries.append((rel, int(size), digest))
    return {"workdir": workdir, "plan_path": plan_path, "manifest_path": manifest_path,
            "plan": plan, "fields": fields, "body": body, "entries": entries,
            "digest": sha256_text(body)}


def source_publish(workdir: Path, *, approve_manifest: str, message: str,
                   remote_name: str = "origin") -> None:
    """First upload of an approved manifest, or a later push of new commits."""
    approve_manifest = one_line(approve_manifest, "--approve-manifest")
    record = read_plan(workdir)
    fields = record["fields"]
    if record["digest"] != approve_manifest:
        fail("--approve-manifest does not match the manifest on disk. Re-read the plan and approve "
             "the digest it prints; the file list may have changed since it was written.")
    recorded_digest = fields["- Manifest SHA-256:"].strip("` ")
    if recorded_digest != record["digest"]:
        fail("The manifest was modified after the plan was written; refusing to publish. Re-plan.")
    project = Path(fields["- Local project path:"].strip("` ")).resolve()
    if not project.is_dir():
        fail(f"The planned local project no longer exists: {project}")
    dest = fields["- Destination:"].strip("` ")
    branch = fields["- Branch:"].strip("` ")
    slug = fields["- Project slug:"].strip("` ")
    check_slug(slug, "project slug")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,120}", branch):
        fail(f"Unsafe branch name in the plan: {branch}")

    missing, changed, total = [], [], 0
    for rel, size, digest in record["entries"]:
        path = project / rel
        if not safe_rel(rel) or path.is_symlink() or not path.is_file():
            missing.append(rel)
            continue
        actual_size = path.stat().st_size
        total += actual_size
        if actual_size != size or sha256_file(path) != digest:
            changed.append(rel)
    if missing or changed:
        fail("The approved file set no longer matches the working tree "
             f"({len(missing)} missing, {len(changed)} changed). Nothing was staged. Re-run "
             "source-plan against the current state and approve the new digest. "
             f"First offenders: {', '.join((missing + changed)[:5])}")
    if total > MAX_SOURCE_TOTAL:
        fail(f"Approved bytes now total {human_bytes(total)}, above the ceiling.")

    fresh_repo = not (project / ".git").is_dir()
    if fresh_repo:
        run_git(project, "init", "-b", branch)
        print(f"Initialized a new Git repository in {project} on branch {branch} (no history existed).")
    else:
        current = run_git(project, "branch", "--show-current", check=False).stdout.strip()
        if not current:
            fail("The project is on a detached HEAD. Check out a named branch before publishing.")
        if current != branch:
            exists = run_git(project, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                             check=False).returncode == 0
            if not exists:
                fail(f"The plan targets branch '{branch}' but the project is on '{current}', and "
                     f"'{branch}' does not exist locally. Refusing to create and populate a branch "
                     f"you did not check out; switch to it (or re-plan with --branch {current}).")
    require_git_identity(project)

    manifest_set = {rel for rel, _size, _digest in record["entries"]}
    unrelated = []
    for entry in (item for item in run_git(project, "status", "--porcelain", "-z",
                                          "--untracked-files=all").stdout.split("\0") if item):
        status, path = entry[:2], entry[3:]
        if status == "??":
            continue  # untracked files are never committed by an explicit-path commit
        if path not in manifest_set:
            unrelated.append(entry)
    if unrelated:
        fail("The project has tracked changes outside the approved manifest. Nothing was staged or "
             "committed. Commit or stash them first: " + "; ".join(unrelated[:5]))

    existing = run_git(project, "remote", "get-url", remote_name, check=False)
    if existing.returncode == 0:
        configured = existing.stdout.strip()
        if configured != dest:
            fail(f"Destination mismatch: this project already has {remote_name} = {configured}, but "
                 f"the approved plan targets {dest}. Refusing to repoint or overwrite it; plan for "
                 "the correct destination or update the remote yourself.")
    else:
        run_git(project, "remote", "add", remote_name, dest)
        print(f"Added remote {remote_name} -> {dest}")

    remote_has_branch = run_git(project, "ls-remote", "--exit-code", "--heads", remote_name,
                                branch, check=False).returncode == 0
    if remote_has_branch:
        run_git(project, "fetch", remote_name, branch, check=False)
        if run_git(project, "merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD",
                   check=False).returncode != 0:
            fail(f"Divergent remote: {remote_name}/{branch} already contains commits that are not "
                 "ancestors of the local HEAD. Refusing to force-push or to merge automatically; "
                 "nothing was staged. Reconcile the two histories deliberately, then rerun.")

    for start in range(0, len(record["entries"]), 100):
        batch = [rel for rel, _size, _digest in record["entries"][start:start + 100]]
        run_git(project, "add", "--", *batch)

    staged = [line for line in run_git(project, "diff", "--cached", "--name-only").stdout.splitlines()
              if line]
    head_ok = run_git(project, "rev-parse", "HEAD", check=False).returncode == 0
    if staged:
        run_git(project, "commit", "-q", "-m", message,
                "--", *[rel for rel, _size, _digest in record["entries"]])
    elif head_ok:
        print("Nothing new to commit from the approved manifest; retrying the push of the existing "
              "commit (no duplicate commit will be created).")
    else:
        fail("No commit exists and the approved manifest produced no staged change; nothing to push.")
    sha = run_git(project, "rev-parse", "HEAD").stdout.strip()

    # The pushed tree — not the manifest — is what actually becomes public, so the two must match.
    head_files = {item for item in run_git(project, "ls-tree", "-r", "--name-only", "-z", sha)
                  .stdout.split("\0") if item}
    extra = sorted(head_files - manifest_set)
    absent = sorted(manifest_set - head_files)
    if extra or absent:
        fail(f"Refusing to push: the commit to be uploaded does not match the approved manifest "
             f"({len(extra)} unapproved tracked file(s), {len(absent)} approved file(s) missing). "
             + (f"Unapproved but present: {', '.join(extra[:8])}. " if extra else "")
             + (f"Approved but absent from the commit: {', '.join(absent[:8])}. " if absent else "")
             + "Remove them from the repository deliberately, or re-plan to include them. "
               "Nothing was pushed.")

    pushed = run_git(project, "push", remote_name, f"HEAD:refs/heads/{branch}", check=False)
    if pushed.returncode:
        detail = (pushed.stderr or pushed.stdout).strip().splitlines()
        fail("Push failed. The local commit and all working files are preserved; fix access and rerun "
             "the same command (no duplicate commit will be created). Git said: "
             + (detail[-1] if detail else "no output"))

    result = (f"# Source publish result — {slug}\n\n"
              f"- Local project path: {project}\n- Destination: {dest}\n- Branch: {branch}\n"
              f"- Published (UTC): {stamp()}\n- Commit SHA: {sha}\n"
              f"- Files in manifest: {len(record['entries'])}\n- Bytes in manifest: {total}\n"
              f"- Manifest SHA-256: {record['digest']}\n- Authorized by: "
              f"{fields['- Authorized by:'].strip()}\n"
              f"- Push result: PUSHED\n"
              f"- Agent readback: not yet performed — run `source-verify --workdir {record['workdir']}`\n"
              "- Independent reviewer access: NOT VERIFIED — run `source-access` after the other "
              "tool actually reads this repository\n\n"
              "This record proves only that this machine pushed. It is not evidence that any other "
              "AI tool can read the repository.\n")
    check_secrets(result)
    (record["workdir"] / SOURCE_RESULT_FILE).write_text(result, encoding="utf-8")
    print(f"PUSHED: {sha}")
    print(f"RESULT WRITTEN: {record['workdir'] / SOURCE_RESULT_FILE}")
    print("Next: source-verify (fresh clone readback), then source-access for each other tool.")


def source_verify(workdir: Path) -> None:
    record = read_plan(workdir)
    result_path = record["workdir"] / SOURCE_RESULT_FILE
    if not result_path.is_file():
        fail(f"No {SOURCE_RESULT_FILE} in the work directory. Run source-publish first.")
    result = read_safe(result_path)
    fields = parse_fields(result, ("- Destination:", "- Branch:", "- Commit SHA:"))
    dest = fields["- Destination:"].strip("` ")
    branch = fields["- Branch:"].strip("` ")
    expected = fields["- Commit SHA:"].strip("` ")
    if not CODE_SHA.fullmatch(expected):
        fail(f"{SOURCE_RESULT_FILE} has no usable commit SHA: {expected!r}")

    clone = Path(tempfile.mkdtemp(prefix="ach-source-verify-"))
    checks: list[tuple[str, str, str]] = []
    try:
        cloned = subprocess.run(["git", "clone", "--branch", branch, "--single-branch", "--quiet",
                                 dest, str(clone)], text=True, encoding="utf-8",
                                errors="surrogateescape", capture_output=True, check=False)
        if cloned.returncode:
            detail = (cloned.stderr or cloned.stdout).strip().splitlines()
            fail("Fresh clone failed, so remote readback is NOT proven: "
                 + (detail[-1] if detail else "no output"))
        remote_sha = run_git(clone, "rev-parse", "HEAD").stdout.strip()
        checks.append(("fresh clone commit SHA", expected,
                       "PASS" if remote_sha == expected else f"FAIL (clone has {remote_sha})"))
        total = 0
        mismatched = []
        for rel, _size, digest in record["entries"]:
            path = clone / rel
            if not path.is_file():
                mismatched.append(f"{rel} (missing)")
                continue
            if sha256_file(path) != digest:
                mismatched.append(f"{rel} (content differs)")
            total += path.stat().st_size
        checks.append(("manifest files present and byte-identical",
                       f"{len(record['entries'])} files",
                       "PASS" if not mismatched else f"FAIL: {', '.join(mismatched[:5])}"))
        checks.append(("no extra tracked files beyond the manifest", str(len(record["entries"])),
                       "PASS" if len(run_git(clone, "ls-files").stdout.splitlines())
                       == len(record["entries"])
                       else f"FAIL ({len(run_git(clone, 'ls-files').stdout.splitlines())} tracked)"))
    finally:
        shutil.rmtree(clone, ignore_errors=True)

    access_status = "NOT YET RECORDED"
    access_path = record["workdir"] / SOURCE_ACCESS_FILE
    if access_path.is_file():
        access_status = read_safe(access_path).strip().splitlines()[-1] if \
            read_safe(access_path).strip() else access_status
    lines = [f"# Source readback verification — {record['fields']['- Project slug:'].strip()}", "",
             f"- Verified (UTC): {stamp()}", f"- Destination: {dest}", f"- Branch: {branch}",
             f"- Expected commit SHA: {expected}", "", "## Checks", ""]
    lines += [f"- {name}: {want} -> {state}" for name, want, state in checks]
    failed = [name for name, _want, state in checks if not state.startswith("PASS")]
    lines += ["", "## Verdict", "",
              f"- Agent (this tool) push + fresh-clone readback: "
              f"{'VERIFIED' if not failed else 'FAILED'}",
              "- Independent reviewer read: NOT VERIFIED by this command. Third-party access is "
              "recorded separately with `source-access`. Do not present this readback as proof that "
              "another AI tool can read the repository.",
              f"- Latest access record: {access_status}"]
    body = "\n".join(lines) + "\n"
    check_secrets(body)
    (record["workdir"] / SOURCE_VERIFY_FILE).write_text(body, encoding="utf-8")
    print(body)
    print(f"VERIFY WRITTEN: {record['workdir'] / SOURCE_VERIFY_FILE}")
    if failed:
        raise HubError("Readback verification failed: " + ", ".join(failed))


def source_access(workdir: Path, *, tool: str, status: str, evidence: str,
                  sha: str = "") -> None:
    tool = check_slug(tool, "tool name")
    if status not in SOURCE_TOOL_STATUS:
        fail(f"--status must be one of: {', '.join(SOURCE_TOOL_STATUS)}")
    evidence = one_line(evidence, "--evidence")
    workdir = workdir.expanduser().resolve()
    if not (workdir / SOURCE_PLAN_FILE).is_file():
        fail(f"No source onboarding plan in {workdir}; run source-plan first.")
    path = workdir / SOURCE_ACCESS_FILE
    header = ("# Independent read access — recorded per tool\n\n"
              "Each line is one tool's *own* verification that it can read the source repository.\n"
              "This tool cannot perform that check for another product, so it must never be "
              "inferred from the pushing machine.\n\n"
              "| when (UTC) | tool | status | commit | evidence |\n"
              "| --- | --- | --- | --- | --- |\n")
    line = f"| {stamp()} | {tool} | {status} | {sha.strip() or '-'} | {evidence} |\n"
    check_secrets(line)
    if path.is_file():
        text = read_safe(path)
        if header.splitlines()[0] not in text:
            fail(f"{SOURCE_ACCESS_FILE} is not in the expected format; refusing to append.")
        path.write_text(text.rstrip("\n") + "\n" + line, encoding="utf-8")
    else:
        path.write_text(header + line, encoding="utf-8")
    print(f"RECORDED: {tool} -> {status}")
    print(render_access_summary(workdir))
    print(f"ACCESS WRITTEN: {path}")


def render_access_summary(workdir: Path) -> str:
    plan = read_safe(workdir / SOURCE_PLAN_FILE)
    slug = parse_fields(plan, ("- Project slug:",)).get("- Project slug:", "").strip()
    verify_ok = False
    verify_path = workdir / SOURCE_VERIFY_FILE
    if verify_path.is_file():
        verify_ok = "push + fresh-clone readback: VERIFIED" in read_safe(verify_path)
    tools: dict[str, str] = {}
    access_path = workdir / SOURCE_ACCESS_FILE
    if access_path.is_file():
        for line in read_safe(access_path).splitlines():
            if not line.startswith("| "):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 3 and cells[1] not in ("tool", "---"):
                tools[cells[1]] = cells[2]
    independent = [name for name, state in tools.items() if state == "verified"]
    lines = [f"SOURCE SHARING STATUS — {slug}",
             f"  agent push + fresh-clone readback : {'VERIFIED' if verify_ok else 'NOT VERIFIED'}"]
    if tools:
        for name in sorted(tools):
            lines.append(f"  independent read ({name}){'':<{max(0, 12 - len(name))}}: {tools[name]}")
    else:
        lines.append("  independent read                  : NOT RECORDED for any tool")
    if verify_ok and independent:
        lines.append(f"  VERDICT: sharing VERIFIED with {', '.join(sorted(independent))}")
    else:
        lines.append("  VERDICT: sharing NOT VERIFIED — a successful read by the pushing machine "
                     "does not prove another tool can read this repository")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
    h.add_argument("--status", choices=HANDOFF_STATUS, default="REPORTED_UNVERIFIED")
    h.add_argument("--source-repo", default="", help="Implementation source repository URL")
    h.add_argument("--branch", default="")
    h.add_argument("--code-sha", default="")
    h.add_argument("--pr", default="", help="Pull request URL, or NOT_OPENED")
    h.add_argument("--build", default="", help="Build / run instructions")
    h.add_argument("--tests", default="", help="Actual test command output summary")
    h.add_argument("--acceptance", choices=("PENDING", "PASSED"), default="")
    h.add_argument("--uat", default="", help="UAT feedback id required for PASSED")
    v = sub.add_parser("validate", help="Validate project context and secret markers")
    v.add_argument("--project", required=True)
    sub.add_parser("sync-pull", help="Fast-forward from origin; never overwrite tracked changes")
    s = sub.add_parser("sync-push", help="Push only new independent handoffs")
    s.add_argument("--project", required=True)

    t = sub.add_parser("task-new", help="Create a draft task packet (approved scope required)")
    t.add_argument("--project", required=True)
    t.add_argument("--task", required=True)
    t.add_argument("--title", required=True)
    t.add_argument("--accountable", required=True)
    t.add_argument("--source-repo", required=True)
    t.add_argument("--scope", required=True)
    t.add_argument("--expected", required=True)
    t.add_argument("--revision", default="v1")
    t.add_argument("--baseline-sha", default="")
    t.add_argument("--request", default="")
    t.add_argument("--out-of-scope", default="")
    t.add_argument("--evidence", default="")
    t.add_argument("--criterion", action="append", default=[])
    ta = sub.add_parser("task-approve", help="Record the human approval publication depends on")
    ta.add_argument("--project", required=True)
    ta.add_argument("--task", required=True)
    ta.add_argument("--approved-by", required=True)
    ta.add_argument("--statement", required=True)
    ts = sub.add_parser("task-asset", help="Register an approved image asset with its hash")
    ts.add_argument("--project", required=True)
    ts.add_argument("--task", required=True)
    ts.add_argument("--file", required=True)
    ts.add_argument("--origin", required=True)
    ts.add_argument("--approved-by", required=True)
    tp = sub.add_parser("task-publish", help="Publish an approved packet; never overwrites")
    tp.add_argument("--project", required=True)
    tp.add_argument("--task", required=True)
    tr = sub.add_parser("task-read", help="Read a packet and verify its manifest")
    tr.add_argument("--project", required=True)
    tr.add_argument("--task", required=True)
    tr.add_argument("--sync", action="store_true")

    u = sub.add_parser("uat-new", help="Record a standardized UAT defect report")
    u.add_argument("--project", required=True)
    u.add_argument("--task", required=True)
    u.add_argument("--reporter", required=True)
    u.add_argument("--source-repo", required=True)
    u.add_argument("--tested-commit", required=True)
    u.add_argument("--environment", required=True)
    u.add_argument("--steps", required=True)
    u.add_argument("--expected", required=True)
    u.add_argument("--observed", required=True)
    u.add_argument("--severity", required=True, choices=UAT_SEVERITY)
    u.add_argument("--impact", default="")
    u.add_argument("--logs", default="")
    u.add_argument("--related-pr", default="")
    u.add_argument("--related-handoff", default="")
    u.add_argument("--screenshot", default="")
    u.add_argument("--screenshot-origin", default="")
    us = sub.add_parser("uat-status", help="Append a status transition to a UAT record")
    us.add_argument("--project", required=True)
    us.add_argument("--feedback", required=True)
    us.add_argument("--status", required=True, choices=UAT_STATUS)
    us.add_argument("--by", required=True)
    us.add_argument("--note", default="")
    us.add_argument("--related-pr", default="")
    up = sub.add_parser("uat-publish", help="Publish a UAT record append-only")
    up.add_argument("--project", required=True)
    up.add_argument("--feedback", required=True)
    ur = sub.add_parser("uat-read", help="Read UAT feedback records")
    ur.add_argument("--project", required=True)
    ur.add_argument("--feedback", default="")
    ur.add_argument("--sync", action="store_true")

    o = sub.add_parser("onboard-check", help="Verify source read, push and connector access")
    o.add_argument("--source-repo", default="")
    o.add_argument("--prove-push", action="store_true")

    si = sub.add_parser("source-inspect",
                        help="Read-only inspection of a local project before onboarding")
    si.add_argument("--path", required=True, help="Absolute path of the local project")
    si.add_argument("--include", action="append", default=[],
                    help="Extra path/glob to consider (repeatable)")
    si.add_argument("--out", default="", help="Also write the report to this file")
    si.add_argument("--manifest-out", default="",
                    help="Also write the candidate file list (review copy, not an approval)")
    sp = sub.add_parser("source-plan",
                        help="Plan a first upload: exact file list + owner authorization")
    sp.add_argument("--path", required=True)
    sp.add_argument("--project", required=True, help="Context project slug")
    sp.add_argument("--dest", required=True, help="Destination private repository URL")
    sp.add_argument("--workdir", required=True,
                    help="Existing directory OUTSIDE the project that holds the plan")
    sp.add_argument("--authorize", required=True, help="Owner who authorizes this upload")
    sp.add_argument("--statement", required=True, help="Authorization statement")
    sp.add_argument("--branch", default="",
                    help="Target branch; defaults to the project's current branch (or main)")
    sp.add_argument("--include", action="append", default=[])
    sp.add_argument("--allow-review", action="append", default=[],
                    help="Glob promoting a review-required file into the manifest")
    spp = sub.add_parser("source-publish",
                         help="Non-destructive first upload of an approved manifest")
    spp.add_argument("--workdir", required=True)
    spp.add_argument("--approve-manifest", required=True, help="Digest printed by source-plan")
    spp.add_argument("--message", default="Initial application source upload")
    sv = sub.add_parser("source-verify",
                        help="Fresh-clone read-back of the published commit")
    sv.add_argument("--workdir", required=True)
    sa = sub.add_parser("source-access",
                        help="Record one other tool's own read access to the source repo")
    sa.add_argument("--workdir", required=True)
    sa.add_argument("--tool", required=True, help="Tool name being verified (e.g. chatgpt)")
    sa.add_argument("--status", required=True, choices=SOURCE_TOOL_STATUS)
    sa.add_argument("--evidence", required=True, help="What that tool actually did")
    sa.add_argument("--sha", default="")

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
                          args.evidence, args.risks, args.next_step, args.status,
                          source_repo=args.source_repo, branch=args.branch,
                          code_sha=args.code_sha, pr=args.pr, build=args.build,
                          tests=args.tests, acceptance=args.acceptance, uat=args.uat)
        elif args.command == "validate":
            return validate(root, args.project)
        elif args.command == "sync-pull":
            pull(root)
        elif args.command == "sync-push":
            sync_push(root, args.project)
        elif args.command == "task-new":
            task_new(root, args.project, args.task, title=args.title, revision=args.revision,
                     accountable=args.accountable, source_repo=args.source_repo,
                     baseline_sha=args.baseline_sha, scope=args.scope,
                     out_of_scope=args.out_of_scope, expected=args.expected,
                     request=args.request, evidence=args.evidence, criteria=args.criterion)
        elif args.command == "task-approve":
            task_approve(root, args.project, args.task, approved_by=args.approved_by,
                         statement=args.statement)
        elif args.command == "task-asset":
            task_add_asset(root, args.project, args.task, args.file, origin=args.origin,
                           approved_by=args.approved_by)
        elif args.command == "task-publish":
            task_publish(root, args.project, args.task)
        elif args.command == "task-read":
            print(task_read(root, args.project, args.task, do_sync=args.sync))
        elif args.command == "uat-new":
            uat_new(root, args.project, task_id=args.task, reporter=args.reporter,
                    source_repo=args.source_repo, tested_commit=args.tested_commit,
                    environment=args.environment, steps=args.steps, expected=args.expected,
                    observed=args.observed, impact=args.impact, severity=args.severity,
                    logs=args.logs, related_pr=args.related_pr,
                    related_handoff=args.related_handoff,
                    screenshot=Path(args.screenshot) if args.screenshot else None,
                    screenshot_origin=args.screenshot_origin)
        elif args.command == "uat-status":
            uat_status(root, args.project, args.feedback, status=args.status, by=args.by,
                       note=args.note, related_pr=args.related_pr)
        elif args.command == "uat-publish":
            uat_publish(root, args.project, args.feedback)
        elif args.command == "uat-read":
            print(uat_read(root, args.project, args.feedback or None, do_sync=args.sync))
        elif args.command == "onboard-check":
            return onboard_check(root, source_repo=args.source_repo, prove_push=args.prove_push)
        elif args.command == "source-inspect":
            report = source_inspect(source_project_path(args.path), tuple(args.include),
                                    Path(args.manifest_out) if args.manifest_out else None)
            print(report)
            if args.out:
                target = Path(args.out).expanduser()
                if target.exists():
                    fail(f"Refusing to overwrite the existing report: {target}")
                target.write_text(report + "\n", encoding="utf-8")
                print(f"\nREPORT WRITTEN: {target}")
        elif args.command == "source-plan":
            source_plan(source_project_path(args.path), args.project, args.dest,
                        Path(args.workdir), authorize=args.authorize, statement=args.statement,
                        includes=tuple(args.include), allow_review=tuple(args.allow_review),
                        branch=args.branch)
        elif args.command == "source-publish":
            source_publish(Path(args.workdir), approve_manifest=args.approve_manifest,
                           message=args.message)
        elif args.command == "source-verify":
            source_verify(Path(args.workdir))
        elif args.command == "source-access":
            source_access(Path(args.workdir), tool=args.tool, status=args.status,
                          evidence=args.evidence, sha=args.sha)
    except HubError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
