import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ach


def git(directory, *args):
    return subprocess.run(["git", "-C", str(directory), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_init_read_handoff_validate(self):
        ach.make_project(self.root, "example", "Example")
        with contextlib.redirect_stdout(io.StringIO()):
            file = ach.write_handoff(self.root, "example", "codex", "check", "done",
                                     "ran tests", "none", "share review", "VERIFIED")
        self.assertTrue(file.exists())
        self.assertIn("ran tests", ach.render_context(self.root, "example", 5))
        self.assertEqual(0, ach.validate(self.root, "example"))

    def test_invalid_slugs_and_secret_block(self):
        with self.assertRaises(ach.HubError):
            ach.make_project(self.root, "../escape", "Unsafe")
        ach.make_project(self.root, "safe", "Safe")
        with self.assertRaises(ach.HubError):
            ach.write_handoff(self.root, "safe", "workbuddy", "test", "password=supersecret123",
                              "", "", "", "BLOCKED")
        self.assertEqual([], list((self.root / "projects/safe/handoffs").glob("20*.md")))

    def test_git_two_agents_no_overwrite(self):
        bare = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(bare)],
                       check=True, capture_output=True)
        primary = self.root / "primary"
        git(self.root, "clone", str(bare), str(primary))
        git(primary, "config", "user.email", "test@example.invalid")
        git(primary, "config", "user.name", "Test")
        ach.make_project(primary, "case", "Case")
        git(primary, "add", "projects")
        git(primary, "commit", "-m", "baseline")
        git(primary, "push", "-u", "origin", "main")
        a, b = self.root / "a", self.root / "b"
        git(self.root, "clone", str(bare), str(a))
        git(self.root, "clone", str(bare), str(b))
        for place in (a, b):
            git(place, "config", "user.email", "test@example.invalid")
            git(place, "config", "user.name", "Test")
        with contextlib.redirect_stdout(io.StringIO()):
            ach.write_handoff(a, "case", "workbuddy", "Implement", "Change A", "commit a", "", "review", "VERIFIED")
            ach.write_handoff(b, "case", "codex", "Review", "Change B", "test b", "", "done", "VERIFIED")
            ach.sync_push(a, "case")
            # Agent B had already prepared an independent handoff. It can now
            # refresh and see Agent A's content before writing its own commit.
            current = ach.render_context(b, "case", 10)
            self.assertNotIn("Change A", current)
            ach.pull(b)
            current = ach.render_context(b, "case", 10)
            self.assertIn("Change A", current)
            ach.sync_push(b, "case")
        verifier = self.root / "verifier"
        git(self.root, "clone", str(bare), str(verifier))
        logs = list((verifier / "projects/case/handoffs").glob("20*.md"))
        self.assertEqual(2, len(logs))
        contents = "\n".join(p.read_text() for p in logs)
        self.assertIn("workbuddy", contents)
        self.assertIn("codex", contents)

    def test_sync_refuses_tracked_edits(self):
        repo = self.root / "repo"
        repo.mkdir()
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.email", "test@example.invalid")
        git(repo, "config", "user.name", "Test")
        ach.make_project(repo, "case", "Case")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "initial")
        (repo / "projects/case/CURRENT_STATUS.md").write_text("changed")
        with self.assertRaises(ach.HubError):
            ach.require_clean_for_pull(repo)


if __name__ == "__main__":
    unittest.main()
