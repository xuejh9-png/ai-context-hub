import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ach


class SyncPushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.remote = self.folder / "remote.git"
        self.repo = self.folder / "agent"
        self.other = self.folder / "other"
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.git(self.folder, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.folder, "clone", str(self.remote), str(self.repo))
        self.identity(self.repo)
        ach.make_project(self.repo, "case", "Case")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "baseline")
        self.git(self.repo, "push", "-u", "origin", "main")
        self.git(self.folder, "clone", str(self.remote), str(self.other))
        self.identity(self.other)
        self.git(self.other, "config", "user.name", "Other Agent")
        self.baseline = self.git(self.remote, "rev-parse", "main")

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              text=True, capture_output=True).stdout.strip()

    def identity(self, repo):
        self.git(repo, "config", "user.name", "Test")
        self.git(repo, "config", "user.email", "test@example.invalid")
        self.git(repo, "config", "commit.gpgsign", "false")

    def handoff(self, repo=None, agent="codex"):
        return ach.write_handoff(repo or self.repo, "case", agent, "Review", "done",
                                 "local test", "none", "review", "VERIFIED")

    def assert_unstaged(self, path):
        self.assertTrue(path.exists())
        self.assertEqual("", self.git(self.repo, "diff", "--cached", "--name-only"))
        self.assertEqual(self.baseline, self.git(self.repo, "rev-parse", "HEAD"))

    def test_missing_identity_leaves_index_clean_and_can_retry(self):
        path = self.handoff()
        self.git(self.repo, "config", "user.name", "")
        self.git(self.repo, "config", "user.email", "")
        self.git(self.repo, "config", "user.useConfigOnly", "true")
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assert_unstaged(path)
        self.identity(self.repo)
        ach.sync_push(self.repo, "case")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"),
                         self.git(self.remote, "rev-parse", "main"))

    def test_commit_hook_failure_leaves_index_clean_and_preserves_file(self):
        path = self.handoff()
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assert_unstaged(path)
        hook.write_text("#!/bin/sh\nexit 0\n")
        ach.sync_push(self.repo, "case")
        self.assertIn(path.name, self.git(self.remote, "ls-tree", "-r", "--name-only", "main"))

    def test_rejected_push_is_resumed_without_duplicate_commit(self):
        path = self.handoff()
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        pending = self.git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(self.baseline, pending)
        self.assertEqual(self.baseline, self.git(self.remote, "rev-parse", "main"))
        hook.write_text("#!/bin/sh\nexit 0\n")
        ach.sync_push(self.repo, "case")
        self.assertEqual(pending, self.git(self.remote, "rev-parse", "main"))
        self.assertEqual("2", self.git(self.remote, "rev-list", "--count", "main"))
        self.assertIn(path.name, self.git(self.remote, "ls-tree", "-r", "--name-only", "main"))

    def test_refuses_unrelated_committed_history(self):
        secret = self.repo / "unapproved.txt"
        secret.write_text("unapproved private material")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "unapproved")
        self.handoff()
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assertEqual(self.baseline, self.git(self.remote, "rev-parse", "main"))

    def test_refuses_pending_edit_even_if_final_diff_is_add_only(self):
        path = self.handoff()
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "handoff")
        path.write_text(path.read_text() + "\nchanged after commit\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "edit existing handoff")
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assertEqual(self.baseline, self.git(self.remote, "rev-parse", "main"))

    def test_repeat_success_is_idempotent(self):
        self.handoff()
        ach.sync_push(self.repo, "case")
        sha = self.git(self.remote, "rev-parse", "main")
        ach.sync_push(self.repo, "case")
        self.assertEqual(sha, self.git(self.remote, "rev-parse", "main"))

    def test_pending_secret_is_rejected_before_publication(self):
        path = self.handoff()
        path.write_text(path.read_text() + "\npassword=synthetic_secret_for_test\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "unsafe log")
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assertEqual(self.baseline, self.git(self.remote, "rev-parse", "main"))

    def test_refuses_symlink_and_nested_handoff(self):
        folder = self.repo / "projects/case/handoffs"
        (folder / "linked.md").symlink_to(self.other / "projects/case/DECISIONS.md")
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assertEqual("", self.git(self.repo, "diff", "--cached", "--name-only"))

    def test_handoff_filename_with_spaces_is_not_git_quoted(self):
        path = self.handoff()
        spaced = path.with_name("independent review.md")
        spaced.write_bytes(path.read_bytes())
        ach.sync_push(self.repo, "case")
        self.assertIn("independent review.md",
                      self.git(self.remote, "ls-tree", "-r", "--name-only", "main"))

    def race(self, collision=False):
        local = self.handoff()
        content = local.read_bytes()
        if collision:
            remote_path = self.other / local.relative_to(self.repo)
            remote_path.write_bytes(content)
        else:
            remote_path = self.handoff(self.other, "workbuddy")
        original = ach.run_git
        fired = False

        def intercept(root, *args, **kwargs):
            nonlocal fired
            if root == self.repo and args[0] == "push" and not fired:
                fired = True
                ach.sync_push(self.other, "case")
            return original(root, *args, **kwargs)

        with mock.patch.object(ach, "run_git", side_effect=intercept):
            if collision:
                with self.assertRaises(ach.HubError):
                    ach.sync_push(self.repo, "case")
            else:
                ach.sync_push(self.repo, "case")
        self.assertTrue(fired)
        self.assertEqual(content, local.read_bytes())
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())
        return local, remote_path

    def test_real_push_race_preserves_both_logs_and_original_commit(self):
        local, remote_path = self.race()
        verifier = self.folder / "verifier"
        self.git(self.folder, "clone", str(self.remote), str(verifier))
        self.assertEqual(local.read_bytes(), (verifier / local.relative_to(self.repo)).read_bytes())
        self.assertEqual(remote_path.read_bytes(), (verifier / remote_path.relative_to(self.other)).read_bytes())
        # Successful recovery appends a merge; it must not rewrite the handoff commit.
        self.assertEqual("4", self.git(self.remote, "rev-list", "--count", "main"))

    def test_same_filename_race_fails_even_for_identical_bytes(self):
        self.race(collision=True)
        self.assertNotEqual(self.git(self.repo, "rev-parse", "HEAD"),
                            self.git(self.remote, "rev-parse", "main"))

    def test_same_checkout_lock_refuses_second_writer(self):
        path = self.handoff()
        (self.repo / ".git/ach-sync.lock").write_text("another sync is running")
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assert_unstaged(path)
        with self.assertRaises(ach.HubError):
            ach.pull(self.repo)

    def test_failed_fetch_does_not_stage_or_commit(self):
        path = self.handoff()
        self.git(self.repo, "remote", "set-url", "origin", str(self.folder / "absent.git"))
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assert_unstaged(path)

    def test_refuses_unrelated_untracked_and_tracked_changes(self):
        self.handoff()
        unrelated = self.repo / "unrelated.txt"
        unrelated.write_text("outside handoffs")
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.git(self.repo, "add", "unrelated.txt")
        with self.assertRaises(ach.HubError):
            ach.sync_push(self.repo, "case")
        self.assertEqual(self.baseline, self.git(self.remote, "rev-parse", "main"))


if __name__ == "__main__":
    unittest.main()
