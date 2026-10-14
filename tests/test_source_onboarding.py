"""v0.3: onboarding an existing local project into a separate private source repository.

Every fixture here is synthetic. No real user project, business repository, database,
backup or credential is ever used as a test fixture.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "src"))

import ach  # noqa: E402

IDENTITY_ENV = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL")
PRIVATE_URL = "https://github.com/example/private-app.git"


def api(status: int):
    return lambda slug: status


def reachable(ok: bool, detail: str = "ok"):
    return lambda url: (ok, detail)


class SourceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self._env_before = {key: os.environ.get(key) for key in IDENTITY_ENV}
        os.environ.update({
            "GIT_AUTHOR_NAME": "Source Test", "GIT_AUTHOR_EMAIL": "source@example.invalid",
            "GIT_COMMITTER_NAME": "Source Test",
            "GIT_COMMITTER_EMAIL": "source@example.invalid",
        })
        self.addCleanup(self._restore_env)
        self.output = io.StringIO()
        redirect_out = contextlib.redirect_stdout(self.output)
        redirect_out.__enter__()
        self.addCleanup(redirect_out.__exit__, None, None, None)
        redirect_err = contextlib.redirect_stderr(self.output)
        redirect_err.__enter__()
        self.addCleanup(redirect_err.__exit__, None, None, None)

    def _restore_env(self) -> None:
        for key, value in self._env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # -- git helpers ------------------------------------------------------
    def git(self, repo, *args) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                              capture_output=True).stdout.strip()

    def git_quiet(self, repo, *args) -> str:
        result = subprocess.run(["git", "-C", str(repo), *args], text=True,
                                capture_output=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def remote_files(self, remote, ref: str = "main") -> list[str]:
        return sorted(self.git_quiet(remote, "ls-tree", "-r", "--name-only", ref).splitlines())

    def remote_head(self, remote, ref: str = "main") -> str:
        return self.git_quiet(remote, "rev-parse", ref)

    def remote_count(self, remote, ref: str = "main") -> str:
        return self.git_quiet(remote, "rev-list", "--count", ref)

    def make_remote(self, name: str = "remote.git") -> Path:
        remote = self.root / name
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(remote))
        return remote

    def make_git_project(self, extra_files=None, name: str = "app") -> Path:
        project = self.root / name
        project.mkdir(parents=True, exist_ok=True)
        self.git(project, "init", "-b", "main")
        self.git(project, "config", "user.name", "Source Test")
        self.git(project, "config", "user.email", "source@example.invalid")
        self.git(project, "config", "commit.gpgsign", "false")
        (project / "src").mkdir(parents=True, exist_ok=True)
        (project / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (project / "README.md").write_text("# Synthetic app\n", encoding="utf-8")
        (project / ".gitignore").write_text(".env\n.env.example\n*.sqlite3\nbackups/\n*.bin\n.venv/\n",
                                           encoding="utf-8")
        extras = []
        for rel, content in (extra_files or {}).items():
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")
            extras.append(rel)
        if extras:
            self.git(project, "add", "-f", "--", *extras)
        return project

    def commit_all(self, project, message: str = "commit") -> str:
        self.git(project, "add", "-A")
        self.git(project, "commit", "-q", "-m", message)
        return self.git(project, "rev-parse", "HEAD")

    def snapshot(self, project: Path) -> dict:
        """Content snapshot of the project, excluding Git's own metadata."""
        result = {}
        for base, dirs, files in os.walk(project):
            if ".git" in dirs:
                dirs.remove(".git")
            for name in files:
                path = Path(base) / name
                info = path.stat()
                result[path.relative_to(project).as_posix()] = (info.st_size, info.st_mtime_ns)
        return result

    def plan(self, project: Path, dest, *, slug: str = "demo", work: Path | None = None,
             api_probe=None, remote_probe=None, includes=(), allow_review=(),
             branch="", deny=()) -> str:
        _, digest = ach.source_plan(project, slug, str(dest), work or self.work,
                                   authorize="demo-owner",
                                   statement="approved: first upload of the reviewed file list",
                                   includes=includes, allow_review=allow_review,
                                   branch=branch, api_probe=api_probe, remote_probe=remote_probe,
                                   deny=deny)
        return digest


class SourceInspectTests(SourceFixture):
    def test_inspection_writes_nothing_into_the_project(self):
        project = self.make_git_project()
        self.commit_all(project)
        before = self.snapshot(project)
        report = ach.source_inspect(project)
        self.assertEqual(before, self.snapshot(project))
        self.assertIn("Nothing was written, moved, staged or deleted", report)

    def test_inspection_reports_git_facts(self):
        project = self.make_git_project()
        head = self.commit_all(project)
        report = ach.source_inspect(project)
        self.assertIn(f"HEAD sha             : {head}", report)
        self.assertIn("current branch       : main", report)
        self.assertIn("NONE — nothing has been pushed yet", report)
        self.assertIn("VERDICT: READY for source-plan", report)

    def test_inspection_flags_denied_review_and_untracked(self):
        project = self.make_git_project(extra_files={
            ".env": "TOKEN=should-never-be-uploaded\n",
            "backups/dump.zip": b"PK\x03\x04synthetic",
            "release/bundle.zip": b"PK\x03\x04synthetic",
        })
        self.commit_all(project)
        (project / "notes-untracked.txt").write_text("scratch\n", encoding="utf-8")
        report = ach.source_inspect(project)
        self.assertIn("DENY  .env", report)
        self.assertIn("REVIEW", report)
        self.assertIn("release/bundle.zip", report)
        self.assertIn("notes-untracked.txt", report)
        self.assertIn("VERDICT: BLOCKED", report)

    def test_denied_file_in_history_blocks_planning(self):
        project = self.make_git_project(extra_files={"deploy/id_rsa": "PRIVATE KEY MATERIAL\n"})
        self.commit_all(project, "add a key by mistake")
        (project / "deploy" / "id_rsa").unlink()
        self.commit_all(project, "remove the key")
        report = ach.source_inspect(project)
        self.assertIn("HARD-DENIED IN GIT HISTORY", report)
        self.assertIn("DENY  deploy/id_rsa", report)
        remote = self.make_remote()
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, remote)
        self.assertIn("Git history", str(caught.exception))

    def test_ignored_build_directory_is_listed_but_not_selected(self):
        project = self.make_git_project()
        (project / ".venv" / "lib").mkdir(parents=True)
        (project / ".venv" / "lib" / "big.py").write_text("x = 1\n", encoding="utf-8")
        self.commit_all(project)
        report = ach.source_inspect(project)
        self.assertIn(".venv/", report)
        selection = report.split("--- upload selection ---")[1].split("HARD-DENIED")[0]
        self.assertNotIn(".venv/lib/big.py", selection)


class SourcePlanTests(SourceFixture):
    def test_plan_refuses_hard_denied_file_in_the_selection(self):
        project = self.make_git_project(extra_files={".env": "TOKEN=abc\n"})
        self.commit_all(project)
        remote = self.make_remote()
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, remote)
        self.assertIn("hard-denied", str(caught.exception))
        self.assertFalse((self.work / ach.SOURCE_PLAN_FILE).exists())

    def test_plan_refuses_a_public_github_destination(self):
        project = self.make_git_project()
        self.commit_all(project)
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, PRIVATE_URL, api_probe=api(200), remote_probe=reachable(True))
        self.assertIn("PUBLIC", str(caught.exception))

    def test_plan_refuses_a_github_destination_that_cannot_be_reached(self):
        project = self.make_git_project()
        self.commit_all(project)
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, PRIVATE_URL, api_probe=api(404),
                      remote_probe=reachable(False, "fatal: repository not found"))
        self.assertIn("does not exist yet or this machine lacks credentials",
                      str(caught.exception))

    def test_plan_accepts_a_private_github_destination(self):
        project = self.make_git_project()
        self.commit_all(project)
        digest = self.plan(project, PRIVATE_URL, api_probe=api(404), remote_probe=reachable(True))
        plan = (self.work / ach.SOURCE_PLAN_FILE).read_text(encoding="utf-8")
        self.assertIn("verified private", plan)
        self.assertIn(digest, plan)

    def test_plan_refuses_a_missing_local_destination(self):
        project = self.make_git_project()
        self.commit_all(project)
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, self.root / "absent.git")
        self.assertIn("local destination does not exist", str(caught.exception))

    def test_plan_requires_the_workdir_to_be_outside_the_project(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        inside = project / "workdir"
        inside.mkdir()
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, remote, work=inside)
        self.assertIn("OUTSIDE the inspected project", str(caught.exception))

    def test_plan_requires_a_named_authorizer(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        with self.assertRaises(ach.HubError):
            ach.source_plan(project, "demo", str(remote), self.work, authorize="",
                            statement="approved", includes=(), allow_review=(), branch="main")

    def test_plan_excludes_review_items_until_explicitly_promoted(self):
        project = self.root / "plain-review"
        (project / "src").mkdir(parents=True)
        (project / "src" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
        (project / "release").mkdir()
        (project / "release" / "bundle.zip").write_bytes(b"PK\x03\x04data")
        remote = self.make_remote()
        self.plan(project, remote, branch="main")
        manifest = (self.work / ach.SOURCE_MANIFEST_FILE).read_text(encoding="utf-8")
        self.assertNotIn("release/bundle.zip", manifest)

        fresh = self.root / "work2"
        fresh.mkdir()
        self.plan(project, remote, work=fresh, allow_review=("release/*",), branch="main")
        self.assertIn("release/bundle.zip",
                      (fresh / ach.SOURCE_MANIFEST_FILE).read_text(encoding="utf-8"))


class SourcePublishTests(SourceFixture):
    def test_first_upload_then_fresh_clone_readback(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")

        self.assertEqual([".gitignore", "README.md", "src/main.py"], self.remote_files(remote))
        sha = self.remote_head(remote)
        result = (self.work / ach.SOURCE_RESULT_FILE).read_text(encoding="utf-8")
        self.assertIn(f"- Commit SHA: {sha}", result)
        self.assertIn("Independent reviewer access: NOT VERIFIED", result)

        ach.source_verify(self.work)
        verify = (self.work / ach.SOURCE_VERIFY_FILE).read_text(encoding="utf-8")
        self.assertIn("fresh clone commit SHA", verify)
        self.assertIn("push + fresh-clone readback: VERIFIED", verify)
        self.assertIn("Independent reviewer read: NOT VERIFIED by this command", verify)

    def test_publish_refuses_a_mismatched_manifest_digest(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        self.plan(project, remote)
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest="0" * 64, message="x")
        self.assertIn("does not match the manifest on disk", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_publish_refuses_when_files_changed_after_planning(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        (project / "src" / "main.py").write_text("print('changed after approval')\n",
                                                 encoding="utf-8")
        self.commit_all(project, "sneaky change")
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="x")
        self.assertIn("no longer matches the working tree", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_publish_refuses_when_the_commit_contains_unapproved_files(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        (project / "unapproved.py").write_text("SHOULD_NOT_UPLOAD = True\n", encoding="utf-8")
        self.commit_all(project, "unapproved change after planning")
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="x")
        self.assertIn("History changed after approval", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_publish_refuses_an_existing_different_origin(self):
        project = self.make_git_project()
        self.commit_all(project)
        self.git(project, "remote", "add", "origin", str(self.root / "somewhere-else.git"))
        remote = self.make_remote()
        digest = self.plan(project, remote)
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="x")
        self.assertIn("Destination mismatch", str(caught.exception))

    def test_duplicate_publish_does_not_duplicate_the_commit(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        first = self.remote_head(remote)
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertEqual(first, self.remote_head(remote))
        self.assertEqual(self.git(project, "rev-parse", "HEAD"), self.remote_head(remote))

    def test_failed_first_push_preserves_everything_and_can_be_retried(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        hook = remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        digest = self.plan(project, remote)
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertIn("preserved", str(caught.exception))
        self.assertTrue((project / "src" / "main.py").is_file())
        self.assertTrue((self.work / ach.SOURCE_MANIFEST_FILE).is_file())
        self.assertEqual("", self.remote_head(remote))

        hook.write_text("#!/bin/sh\nexit 0\n")
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertEqual(self.git(project, "rev-parse", "HEAD"), self.remote_head(remote))
        self.assertEqual(self.git(project, "rev-list", "--count", "HEAD"),
                         self.remote_count(remote))

    def test_read_only_remote_blocks_the_push_without_losing_local_work(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        remote.chmod(0o500)
        try:
            with self.assertRaises(ach.HubError):
                ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        finally:
            remote.chmod(0o700)
        self.assertTrue((project / "src" / "main.py").is_file())
        self.assertIn("origin", self.git(project, "remote"))
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertIn("src/main.py", self.remote_files(remote))

    def test_divergent_remote_is_refused_without_force(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        seeder = self.root / "seeder"
        self.git(self.root, "clone", str(remote), str(seeder))
        self.git(seeder, "config", "user.name", "Seeder")
        self.git(seeder, "config", "user.email", "seed@example.invalid")
        (seeder / "other.txt").write_text("unrelated history\n", encoding="utf-8")
        self.commit_all(seeder, "seed unrelated history")
        self.git(seeder, "push", "-q", "origin", "main")
        before = self.remote_head(remote)

        digest = self.plan(project, remote)
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertIn("Divergent remote", str(caught.exception))
        self.assertEqual(before, self.remote_head(remote))

    def test_missing_git_identity_blocks_the_upload(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        for key in IDENTITY_ENV:
            os.environ.pop(key, None)
        self.git(project, "config", "user.name", "")
        self.git(project, "config", "user.email", "")
        self.git(project, "config", "user.useConfigOnly", "true")
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertIn("Git identity is unavailable", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_non_git_project_is_initialised_only_after_approval(self):
        project = self.root / "plain"
        (project / "pkg").mkdir(parents=True)
        (project / "pkg" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
        (project / "setup.txt").write_text("no vcs here\n", encoding="utf-8")
        (project / ".venv").mkdir()
        (project / ".venv" / "junk.py").write_text("junk\n", encoding="utf-8")

        remote = self.make_remote()
        digest = self.plan(project, remote, branch="main")
        self.assertFalse((project / ".git").exists(), "planning must not initialise a repository")
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertTrue((project / ".git").is_dir())
        self.assertEqual(["pkg/mod.py", "setup.txt"], self.remote_files(remote))
        ach.source_verify(self.work)
        self.assertIn("VERIFIED",
                      (self.work / ach.SOURCE_VERIFY_FILE).read_text(encoding="utf-8"))

    def test_publish_refuses_a_branch_the_checkout_is_not_on(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote, branch="release")
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="x")
        self.assertIn("currently on 'main'", str(caught.exception))

    def test_owner_declared_deny_patterns_exclude_files_from_the_manifest(self):
        # A Git-tracked path is necessarily in history, so --deny can only act on files
        # that are not tracked yet: untracked additions, or a non-Git project.
        project = self.root / "plain-with-artifacts"
        (project / "src").mkdir(parents=True)
        (project / "src" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
        (project / "artifacts").mkdir()
        (project / "artifacts" / "shot-01.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")

        report = ach.source_inspect(project, deny=("artifacts/*",))
        self.assertIn("EXCLUDED BY OWNER POLICY", report)
        self.assertIn("POLICY", report)
        self.assertIn("artifacts/shot-01.png", report)

        remote = self.make_remote()
        digest = self.plan(project, remote, deny=("artifacts/*",), branch="main")
        manifest = (self.work / ach.SOURCE_MANIFEST_FILE).read_text(encoding="utf-8")
        self.assertNotIn("artifacts/shot-01.png", manifest)
        self.assertIn("src/main.py", manifest)
        plan = (self.work / ach.SOURCE_PLAN_FILE).read_text(encoding="utf-8")
        self.assertIn("--deny): artifacts/*", plan)
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        self.assertNotIn("artifacts/shot-01.png", self.remote_files(remote))

    def test_owner_declared_deny_pattern_in_history_refuses_the_plan(self):
        project = self.make_git_project(extra_files={"artifacts/shot-01.png": b"PK\x03\x04data"})
        self.commit_all(project)
        remote = self.make_remote()
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, remote, deny=("artifacts/*",))
        message = str(caught.exception)
        self.assertIn("owner-declared policy pattern present in Git history", message)
        self.assertIn("never rewrites history", message)
        self.assertFalse((self.work / ach.SOURCE_MANIFEST_FILE).exists())

    def test_verify_refuses_before_a_publish_has_happened(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        self.plan(project, remote)
        with self.assertRaises(ach.HubError) as caught:
            ach.source_verify(self.work)
        self.assertIn("Run source-publish first", str(caught.exception))


class SourceSnapshotTests(SourceFixture):
    """--mode snapshot publishes only the approved files and never touches local history."""

    def snapshot_plan(self, project: Path, dest, *, work, deny=(), branch="main"):
        _, digest = ach.source_plan(project, "demo", str(dest), work, authorize="demo-owner",
                                   statement="approved: publish only these files",
                                   includes=(), allow_review=(), branch=branch,
                                   deny=deny, mode="snapshot")
        return digest

    def test_snapshot_publishes_only_the_approved_files(self):
        project = self.make_git_project(extra_files={"artifacts/shot-01.png": b"PK\x03\x04data"})
        self.commit_all(project)
        remote = self.make_remote()
        head_before = self.git(project, "rev-parse", "HEAD")
        status_before = self.git(project, "status", "--porcelain")
        count_before = self.git(project, "rev-list", "--count", "HEAD")

        digest = self.snapshot_plan(project, remote, work=self.work, deny=("artifacts/*",))
        manifest = (self.work / ach.SOURCE_MANIFEST_FILE).read_text(encoding="utf-8")
        self.assertNotIn("artifacts/shot-01.png", manifest)
        ach.source_publish(self.work, approve_manifest=digest, message="Snapshot upload")

        published = self.remote_files(remote)
        self.assertIn("src/main.py", published)
        self.assertNotIn("artifacts/shot-01.png", published)
        self.assertEqual("1", self.remote_count(remote))
        # The snapshot is a root commit: it carries no ancestor history.
        self.assertEqual("", self.git(remote, "log", "-1", "--format=%P", "main"))

    def test_snapshot_does_not_modify_the_local_repository(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        before = {
            "head": self.git(project, "rev-parse", "HEAD"),
            "branch": self.git(project, "branch", "--show-current"),
            "status": self.git(project, "status", "--porcelain"),
            "count": self.git(project, "rev-list", "--count", "HEAD"),
        }
        work = self.work
        digest = ach.source_plan(project, "demo", str(remote), work, authorize="demo-owner",
                                 statement="approved", includes=(), allow_review=(),
                                 branch="main", mode="snapshot")[1]
        ach.source_publish(work, approve_manifest=digest, message="Snapshot upload")
        after = {
            "head": self.git(project, "rev-parse", "HEAD"),
            "branch": self.git(project, "branch", "--show-current"),
            "status": self.git(project, "status", "--porcelain"),
            "count": self.git(project, "rev-list", "--count", "HEAD"),
        }
        self.assertEqual(before, after)

    def test_snapshot_chain_fast_forwards_without_force(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        first = ach.source_plan(project, "demo", str(remote), self.work, authorize="demo-owner",
                                statement="approved", includes=(), allow_review=(),
                                branch="main", mode="snapshot")[1]
        ach.source_publish(self.work, approve_manifest=first, message="Snapshot one")
        first_sha = self.remote_head(remote)

        second_work = self.root / "work-two"
        second_work.mkdir()
        (project / "src" / "extra.py").write_text("EXTRA = 1\n", encoding="utf-8")
        self.commit_all(project, "add extra")
        second = ach.source_plan(project, "demo", str(remote), second_work, authorize="demo-owner",
                                 statement="approved", includes=(), allow_review=(),
                                 branch="main", mode="snapshot")[1]
        ach.source_publish(second_work, approve_manifest=second, message="Snapshot two")
        self.assertNotEqual(first_sha, self.remote_head(remote))
        self.assertEqual("2", self.remote_count(remote))
        self.assertEqual(first_sha, self.git(remote, "log", "-1", "--format=%P", "main"))
        self.assertIn("src/extra.py", self.remote_files(remote))

    def test_snapshot_refuses_a_divergent_remote(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        seeder = self.root / "seeder"
        self.git(self.root, "clone", str(remote), str(seeder))
        self.git(seeder, "config", "user.name", "Seeder")
        self.git(seeder, "config", "user.email", "seed@example.invalid")
        (seeder / "other.txt").write_text("unrelated\n", encoding="utf-8")
        self.commit_all(seeder, "seed")
        self.git(seeder, "push", "-q", "origin", "main")
        before = self.remote_head(remote)
        digest = ach.source_plan(project, "demo", str(remote), self.work, authorize="demo-owner",
                                 statement="approved", includes=(), allow_review=(),
                                 branch="main", mode="snapshot")[1]
        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="Snapshot")
        self.assertIn("Divergent remote", str(caught.exception))
        self.assertEqual(before, self.remote_head(remote))


class SourceAccessTests(SourceFixture):
    def test_third_party_read_is_kept_separate_from_our_own_readback(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        ach.source_verify(self.work)

        ach.source_access(self.work, tool="chatgpt", status="pending",
                          evidence="connector not yet pointed at the repository")
        summary = ach.render_access_summary(self.work)
        self.assertIn("agent push + fresh-clone readback : VERIFIED", summary)
        self.assertIn("chatgpt", summary)
        self.assertIn("VERDICT: sharing NOT VERIFIED", summary)

        ach.source_access(self.work, tool="codex", status="verified",
                          evidence="independently cloned the repository and read src/main.py",
                          sha=self.remote_head(remote))
        summary = ach.render_access_summary(self.work)
        self.assertIn("VERDICT: sharing VERIFIED with codex", summary)

    def test_access_requires_a_planned_work_directory_and_valid_status(self):
        with self.assertRaises(ach.HubError):
            ach.source_access(self.work, tool="chatgpt", status="verified", evidence="nope")
        project = self.make_git_project()
        self.commit_all(project)
        self.plan(project, self.make_remote())
        with self.assertRaises(ach.HubError):
            ach.source_access(self.work, tool="chatgpt", status="maybe", evidence="nope")

    def test_verified_access_requires_the_exact_published_commit(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        ach.source_publish(self.work, approve_manifest=digest, message="Initial upload")
        with self.assertRaises(ach.HubError):
            ach.source_access(self.work, tool="codex", status="verified",
                              evidence="synthetic read", sha="0" * 40)
        self.assertFalse((self.work / ach.SOURCE_ACCESS_FILE).exists())


if __name__ == "__main__":
    unittest.main()
