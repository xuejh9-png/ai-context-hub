"""v0.2: the onboarding check must report BLOCKED rather than assume access works."""
from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "src"))

import ach  # noqa: E402
from support import HubFixture  # noqa: E402


class OnboardCheckTests(HubFixture):
    def check(self, **kwargs) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ach.onboard_check(self.repo, **kwargs)
        return code, buffer.getvalue()

    def assert_row(self, output: str, name: str, status: str) -> None:
        self.assertRegex(output, re.compile(rf"^\s*{name}\s+{status}\b", re.M))

    def test_ready_when_context_and_source_are_both_readable(self):
        code, output = self.check(source_repo=str(self.remote))
        self.assertEqual(0, code, output)
        self.assert_row(output, "CONTEXT_READ", "PASS")
        self.assert_row(output, "SOURCE_READ", "PASS")
        self.assert_row(output, "CONNECTOR_READ", "UNKNOWN")
        self.assertIn("VERDICT: READY", output)

    def test_blocked_when_no_source_repository_is_configured(self):
        code, output = self.check(source_repo="")
        self.assertEqual(1, code, output)
        self.assert_row(output, "SOURCE_READ", "NOT_PROVIDED")
        self.assertIn("VERDICT: BLOCKED", output)
        self.assertIn("instead of asking for another ZIP", output)

    def test_blocked_when_the_source_repository_is_unreachable(self):
        code, output = self.check(source_repo=str(self.folder / "absent.git"))
        self.assertEqual(1, code, output)
        self.assert_row(output, "SOURCE_READ", "BLOCKED")
        self.assertIn("VERDICT: BLOCKED", output)

    def test_unpushed_local_history_leaves_push_permission_unproven(self):
        (self.repo / "projects/demo/CURRENT_STATUS.md").write_text("local only")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "unpushed local work")
        code, output = self.check(source_repo=str(self.remote))
        self.assertEqual(1, code, output)
        self.assert_row(output, "CONTEXT_PUSH", "UNKNOWN")
        self.assertIn("never reached origin", output)

    def test_prove_push_writes_reads_back_and_cleans_up(self):
        (self.repo / "projects/demo/CURRENT_STATUS.md").write_text("local only")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", "unpushed local work")
        code, output = self.check(source_repo=str(self.remote), prove_push=True)
        self.assertEqual(0, code, output)
        self.assert_row(output, "CONTEXT_PUSH", "PASS")
        self.assertIn("live push + read-back + cleanup succeeded", output)
        leftovers = self.git(self.remote, "for-each-ref", "--format=%(refname)",
                             "refs/ach-onboard/")
        self.assertEqual("", leftovers)

    def test_blocked_without_a_git_identity(self):
        self.git(self.repo, "config", "user.name", "")
        self.git(self.repo, "config", "user.email", "")
        self.git(self.repo, "config", "user.useConfigOnly", "true")
        code, output = self.check(source_repo=str(self.remote))
        self.assertEqual(1, code, output)
        self.assert_row(output, "GIT_IDENTITY", "BLOCKED")

    def test_blocked_outside_a_git_checkout(self):
        plain = self.folder / "not-a-repo"
        plain.mkdir()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ach.onboard_check(plain, source_repo=str(self.remote), prove_push=False)
        self.assertEqual(1, code)
        self.assert_row(buffer.getvalue(), "CONTEXT_REPO", "BLOCKED")


if __name__ == "__main__":
    import unittest
    unittest.main()
