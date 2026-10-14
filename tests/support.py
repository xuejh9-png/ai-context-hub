"""Shared, synthetic-only fixtures for the AI Context Hub test suite.

Nothing here references a real user, company or private repository. All repositories
are temporary bare remotes created under the OS temp directory.
"""
from __future__ import annotations

import contextlib
import io
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import ach  # noqa: E402


def png_bytes(pad: int = 0) -> bytes:
    """A structurally valid 1x1 red PNG, optionally padded with trailing filler."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00" + b"\xff\x00\x00")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels)
            + chunk(b"IEND", b"") + b"\x00" * pad)


class HubFixture(unittest.TestCase):
    """One bare remote plus one authorised clone, committed and pushed."""

    project = "demo"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.remote = self.folder / "remote.git"
        self.git(self.folder, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.repo = self.folder / "agent"
        self.git(self.folder, "clone", str(self.remote), str(self.repo))
        self.identity(self.repo)
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        quiet = contextlib.redirect_stderr(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        ach.make_project(self.repo, self.project, "Demo")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "baseline")
        self.git(self.repo, "push", "-u", "origin", "main")
        self.baseline = self.git(self.remote, "rev-parse", "main")

    # -- helpers ----------------------------------------------------------
    def git(self, repo, *args) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                              capture_output=True).stdout.strip()

    def identity(self, repo) -> None:
        self.git(repo, "config", "user.name", "Test Agent")
        self.git(repo, "config", "user.email", "test@example.invalid")
        self.git(repo, "config", "commit.gpgsign", "false")

    def clone(self, name: str) -> Path:
        target = self.folder / name
        self.git(self.folder, "clone", str(self.remote), str(target))
        self.identity(target)
        return target

    def make_packet(self, task_id: str = "task-1", title: str = "Demo change",
                    repo: Path | None = None) -> Path:
        repo = repo or self.repo
        return ach.task_new(
            repo, self.project, task_id, title=title, revision="v1", accountable="workbuddy",
            source_repo="https://example.invalid/demo/app.git", baseline_sha="0" * 40,
            scope="Change the demo landing page copy.", out_of_scope="Payment integration.",
            expected="Landing page renders the new copy; tests pass.", request="Update copy.",
            evidence="", criteria=[])

    def register_asset(self, task_id: str = "task-1", name: str = "shot-01.png",
                       payload: bytes | None = None, repo: Path | None = None) -> Path:
        repo = repo or self.repo
        source = self.folder / name
        source.write_bytes(payload if payload is not None else png_bytes())
        return ach.task_add_asset(repo, self.project, task_id, source,
                                  origin="synthetic fixture screenshot",
                                  approved_by="demo-user")

    def approve(self, task_id: str = "task-1", repo: Path | None = None) -> None:
        repo = repo or self.repo
        ach.task_approve(repo, self.project, task_id, approved_by="demo-user",
                         statement="Approved: this revision is the one to build.")

    def remote_tree(self, ref: str = "main") -> str:
        return self.git(self.remote, "ls-tree", "-r", "--name-only", ref)

    def remote_head(self, ref: str = "main") -> str:
        return self.git(self.remote, "rev-parse", ref)

    def assert_fail_closed(self, callable_, *args, **kwargs) -> str:
        """A refused operation must leave the index clean and the remote untouched."""
        before = self.remote_head()
        with self.assertRaises(ach.HubError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual("", self.git(self.repo, "diff", "--cached", "--name-only"))
        self.assertEqual(before, self.remote_head())
        return str(caught.exception)
