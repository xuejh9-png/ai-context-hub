"""v0.2 P1: the standardised UAT feedback loop and its link to code and handoffs."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "src"))

import ach  # noqa: E402
from support import HubFixture, png_bytes  # noqa: E402

CODE_SHA = "1a2b3c4d5e6f7890abcdef1234567890abcdef12"
PR_URL = "https://example.invalid/demo/app/pull/42"


class UatFeedbackTests(HubFixture):
    def report(self, **overrides) -> Path:
        fields = dict(
            task_id="task-1", reporter="demo-user",
            source_repo="https://example.invalid/demo/app.git",
            tested_commit=CODE_SHA, environment="macOS 15 / Python 3.13",
            steps="1. Open the demo page.\n2. Submit the form.\n3. Observe the error banner.",
            expected="The form submits and a confirmation appears.",
            observed="An error banner appears and the data is not saved.",
            impact="Blocking for the demo flow.", severity="high",
            logs="browser console trace attached",
            related_pr=PR_URL, related_handoff="NOT_LINKED",
            screenshot=None, screenshot_origin="",
        )
        fields.update(overrides)
        return ach.uat_new(self.repo, self.project, **fields)

    # -- creation and required evidence ----------------------------------
    def test_new_report_records_every_required_field(self):
        path = self.report()
        text = path.joinpath("UAT_FEEDBACK.md").read_text()
        for marker in ach.UAT_MARKERS:
            self.assertIn(marker, text)
        self.assertIn(f"- Tested commit / build: {CODE_SHA}", text)
        self.assertIn(f"- Related PR: {PR_URL}", text)
        self.assertIn("An error banner appears and the data is not saved.", text)
        self.assertEqual("reported", ach.uat_current_status(text))

    def test_missing_required_evidence_is_refused(self):
        for field in ("source_repo", "tested_commit", "environment", "steps",
                      "expected", "observed"):
            with self.assertRaises(ach.HubError) as caught:
                self.report(**{field: ""})
            self.assertIn(f"--{field.replace('_', '-')}", str(caught.exception))
        with self.assertRaises(ach.HubError):
            self.report(severity="catastrophic")
        with self.assertRaises(ach.HubError):
            self.report(reporter="../escape")

    def test_screenshot_is_attached_with_a_matching_hash(self):
        shot = self.folder / "banner.png"
        shot.write_bytes(png_bytes())
        path = self.report(screenshot=shot, screenshot_origin="demo-user screenshot")
        record = path / "UAT_FEEDBACK.md"
        text = record.read_text()
        manifest = ach.parse_assets((path / "ASSETS.md").read_text())
        digest = ach.sha256_file(path / "assets/banner.png")
        self.assertIn("assets/banner.png", text)
        self.assertIn(digest, text)
        self.assertEqual(digest, manifest["assets/banner.png"]["SHA-256"])
        self.assertIn("demo-user screenshot", text)

    def test_unsafe_screenshot_is_refused(self):
        bad = self.folder / "trace.png"
        bad.write_text("not an image")
        with self.assertRaises(ach.HubError):
            self.report(screenshot=bad)

    def test_secret_in_a_report_is_refused(self):
        with self.assertRaises(ach.HubError) as caught:
            self.report(logs="password=supersecret123")
        self.assertIn("credential", str(caught.exception))

    # -- publication ------------------------------------------------------
    def test_report_publishes_and_a_fresh_clone_reads_it(self):
        self.report()
        ach.uat_publish(self.repo, self.project, self.feedback_id())
        verifier = self.clone("verifier")
        listing = ach.uat_read(verifier, self.project, None, do_sync=False)
        self.assertIn("- Status: reported", listing)
        detail = ach.uat_read(verifier, self.project, self.feedback_id(), do_sync=False)
        self.assertIn(f"Tested commit / build: {CODE_SHA}", detail)
        self.assertIn("Current status: reported", detail)

    def test_status_transitions_are_appended_and_old_history_survives(self):
        self.report()
        feedback = self.feedback_id()
        for status in ("reproduced", "fixed", "re-tested"):
            ach.uat_status(self.repo, self.project, feedback, status=status, by="codex",
                           note=f"moved to {status}", related_pr=PR_URL)
        text = (self.repo / "projects/demo/uat" / feedback / "UAT_FEEDBACK.md").read_text()
        history = ach.uat_history(text)
        self.assertEqual(["reported", "reproduced", "fixed", "re-tested"],
                         [entry.split("|")[1].strip() for entry in history])
        self.assertEqual("re-tested", ach.uat_current_status(text))
        ach.uat_publish(self.repo, self.project, feedback)
        published = self.git(self.remote, "show",
                             f"main:projects/demo/uat/{feedback}/UAT_FEEDBACK.md")
        self.assertEqual(text, published + "\n")

    def test_duplicate_status_is_refused(self):
        self.report()
        feedback = self.feedback_id()
        message = self.assert_fail_closed(ach.uat_status, self.repo, self.project, feedback,
                                          status="reported", by="codex", note="", related_pr="")
        self.assertIn("already", message)

    def test_status_requires_an_author_and_a_valid_value(self):
        self.report()
        feedback = self.feedback_id()
        self.assert_fail_closed(ach.uat_status, self.repo, self.project, feedback,
                                status="fixed", by="", note="", related_pr="")

    def test_rewriting_published_history_fails_closed(self):
        self.report()
        feedback = self.feedback_id()
        ach.uat_publish(self.repo, self.project, feedback)
        record = self.repo / "projects/demo/uat" / feedback / "UAT_FEEDBACK.md"
        record.write_text(record.read_text().replace(
            "An error banner appears and the data is not saved.",
            "Nothing to see here."))
        message = self.assert_fail_closed(ach.uat_publish, self.repo, self.project, feedback)
        self.assertIn("append-only", message)

    def test_deleting_a_published_report_file_fails_closed(self):
        shot = self.folder / "banner.png"
        shot.write_bytes(png_bytes())
        feedback_path = self.report(screenshot=shot, screenshot_origin="demo")
        feedback = feedback_path.name
        ach.uat_publish(self.repo, self.project, feedback)
        (feedback_path / "assets/banner.png").unlink()
        message = self.assert_fail_closed(ach.uat_publish, self.repo, self.project, feedback)
        self.assertIn("append-only", message)

    def test_adding_a_new_screenshot_to_a_published_report_is_allowed(self):
        feedback_path = self.report()
        feedback = feedback_path.name
        ach.uat_publish(self.repo, self.project, feedback)
        extra = self.folder / "after-fix.png"
        extra.write_bytes(png_bytes(pad=3))
        (feedback_path / "assets/after-fix.png").write_bytes(extra.read_bytes())
        manifest = feedback_path / "ASSETS.md"
        existing = manifest.read_text() if manifest.is_file() else (
            f"# Approved assets — UAT {feedback}\n")
        manifest.write_text(existing + (
            "\n## assets/after-fix.png\n"
            f"- SHA-256: {ach.sha256_file(extra)}\n"
            f"- Bytes: {extra.stat().st_size}\n- Type: image/png\n"
            "- Origin: retest screenshot\n- Approved by: demo-user\n"
            f"- Added (UTC): {ach.stamp()}\n"))
        ach.uat_status(self.repo, self.project, feedback, status="reproduced", by="codex",
                       note="reproduced with added evidence", related_pr=PR_URL)
        ach.uat_status(self.repo, self.project, feedback, status="fixed", by="codex",
                       note="regression fixed", related_pr=PR_URL)
        ach.uat_publish(self.repo, self.project, feedback)
        tree = self.remote_tree()
        self.assertIn(f"projects/demo/uat/{feedback}/assets/after-fix.png", tree)
        self.assertIn(f"projects/demo/uat/{feedback}/ASSETS.md", tree)
        ach.uat_publish(self.repo, self.project, feedback)  # idempotent

    def test_repeated_publish_is_idempotent(self):
        feedback_path = self.report()
        feedback = feedback_path.name
        ach.uat_publish(self.repo, self.project, feedback)
        head = self.remote_head()
        ach.uat_publish(self.repo, self.project, feedback)
        self.assertEqual(head, self.remote_head())

    def test_publish_requires_a_real_remote(self):
        self.report()
        feedback = self.feedback_id()
        self.git(self.repo, "remote", "set-url", "origin", str(self.folder / "absent.git"))
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, feedback)

    def feedback_id(self) -> str:
        folder = self.repo / "projects/demo/uat"
        return sorted(path.name for path in folder.iterdir() if path.is_dir())[-1]


class HandoffCompletionRecordTests(HubFixture):
    """A completion record must carry real code references and an honest UAT state."""

    def test_implementation_record_requires_real_references(self):
        with self.assertRaises(ach.HubError) as caught:
            ach.write_handoff(self.repo, self.project, "workbuddy", "Implement", "done",
                              "tests pass", "", "review", "VERIFIED",
                              source_repo="https://example.invalid/app.git")
        self.assertIn("--branch", str(caught.exception))
        with self.assertRaises(ach.HubError) as caught:
            ach.write_handoff(self.repo, self.project, "workbuddy", "Implement", "done",
                              "tests pass", "", "review", "VERIFIED",
                              source_repo="https://example.invalid/app.git",
                              branch="feat/x", code_sha="abc123")
        self.assertIn("real 7-40 character hex", str(caught.exception))

    def test_ai_completion_alone_cannot_declare_human_acceptance(self):
        with self.assertRaises(ach.HubError) as caught:
            ach.write_handoff(self.repo, self.project, "workbuddy", "Implement", "done",
                              "tests pass", "", "review", "VERIFIED",
                              source_repo="https://example.invalid/app.git",
                              branch="feat/x", code_sha=CODE_SHA, pr=PR_URL,
                              acceptance="PASSED")
        self.assertIn("human UAT passed", str(caught.exception))

    def test_handoff_records_sha_build_tests_and_pending_uat(self):
        path = ach.write_handoff(
            self.repo, self.project, "workbuddy", "Implement task-1", "Changed the copy",
            "commit " + CODE_SHA, "None", "Hand to Codex", "VERIFIED",
            source_repo="https://example.invalid/demo/app.git", branch="feat/task-1",
            code_sha=CODE_SHA, pr=PR_URL, build="python -m unittest discover -s tests -v",
            tests="Ran 24 tests ... OK", acceptance="PENDING")
        text = path.read_text()
        for marker in ach.HANDOFF_IMPL_MARKERS:
            self.assertIn(marker, text)
        self.assertIn("- Code SHA: " + CODE_SHA, text)
        self.assertIn("- PR: " + PR_URL, text)
        self.assertIn("Human acceptance: PENDING", text)
        self.assertIn("human UAT outstanding", text)
        self.assertEqual(0, ach.validate(self.repo, self.project))

    def test_passed_acceptance_requires_a_retested_uat_record(self):
        report = ach.uat_new(
            self.repo, self.project, task_id="task-1", reporter="demo-user",
            source_repo="https://example.invalid/demo/app.git", tested_commit=CODE_SHA,
            environment="macOS 15", steps="1. reproduce", expected="no error",
            observed="error", impact="", severity="high", logs="", related_pr=PR_URL,
            related_handoff="NOT_LINKED", screenshot=None, screenshot_origin="")
        feedback = report.name
        with self.assertRaises(ach.HubError) as caught:
            ach.write_handoff(self.repo, self.project, "workbuddy", "Implement", "done",
                              "tests pass", "", "review", "VERIFIED",
                              source_repo="https://example.invalid/demo/app.git",
                              branch="feat/x", code_sha=CODE_SHA, pr=PR_URL,
                              acceptance="PASSED", uat=feedback)
        self.assertIn("not 're-tested'", str(caught.exception))
        ach.uat_status(self.repo, self.project, feedback, status="reproduced", by="codex",
                       note="reproduced locally", related_pr="")
        ach.uat_status(self.repo, self.project, feedback, status="fixed", by="codex",
                       note="fixed in PR", related_pr=PR_URL)
        ach.uat_status(self.repo, self.project, feedback, status="re-tested", by="demo-user",
                       note="retest passed on the fixed build", related_pr=PR_URL)
        path = ach.write_handoff(self.repo, self.project, "workbuddy", "Implement", "done",
                                 "tests pass", "", "review", "VERIFIED",
                                 source_repo="https://example.invalid/demo/app.git",
                                 branch="feat/x", code_sha=CODE_SHA, pr=PR_URL,
                                 build="python -m unittest discover -s tests -v",
                                 tests="All synthetic tests passed",
                                 acceptance="PASSED", uat=feedback)
        self.assertIn(f"Human acceptance: PASSED (UAT feedback {feedback})", path.read_text())

    def test_context_index_lists_packets_and_feedback(self):
        self.make_packet()
        self.approve()
        report = ach.uat_new(
            self.repo, self.project, task_id="task-1", reporter="demo-user",
            source_repo="https://example.invalid/demo/app.git", tested_commit=CODE_SHA,
            environment="macOS 15", steps="1. reproduce", expected="no error",
            observed="error", impact="", severity="low", logs="", related_pr="",
            related_handoff="", screenshot=None, screenshot_origin="")
        rendered = ach.render_context(self.repo, self.project, 5)
        self.assertIn("Task packets: task-1 (approved)", rendered)
        self.assertIn(f"UAT feedback: {report.name} [reported]", rendered)


if __name__ == "__main__":
    import unittest
    unittest.main()
