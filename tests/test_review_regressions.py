"""Independent approval, UAT integrity and recovery regressions; synthetic data only."""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from support import HubFixture, ach, png_bytes

SOURCE = "https://example.invalid/demo/app.git"
CODE = "a" * 40


class ReviewRegressions(HubFixture):
    def report(self, screenshot=None):
        return ach.uat_new(
            self.repo, self.project, task_id="task-1", reporter="demo-user",
            source_repo=SOURCE, tested_commit=CODE, environment="test environment",
            steps="Open demo", expected="Success", observed="Failure", impact="",
            severity="high", logs="", related_pr="", related_handoff="",
            screenshot=screenshot, screenshot_origin="synthetic image")

    def commit(self, message):
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-m", message)

    def test_acceptance_edit_between_approval_and_first_publish_is_rejected(self):
        folder = self.make_packet()
        self.approve()
        path = folder / "ACCEPTANCE.md"
        path.write_text(path.read_text() + "\n- [ ] AC-4: unapproved criterion\n")
        self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")

    def test_manifest_metadata_edit_after_approval_is_rejected(self):
        folder = self.make_packet()
        self.register_asset()
        self.approve()
        path = folder / "ASSETS.md"
        path.write_text(path.read_text().replace("synthetic fixture screenshot", "changed provenance"))
        self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")

    def test_new_asset_after_approval_is_rejected_without_writing(self):
        folder = self.make_packet()
        self.approve()
        self.assert_fail_closed(self.register_asset)
        self.assertFalse((folder / "assets/shot-01.png").exists())

    def test_invalid_approval_hash_cannot_disable_verification(self):
        folder = self.make_packet()
        self.approve()
        path = folder / "APPROVAL.md"
        digest = ach.sha256_file(folder / "BRIEF.md")
        path.write_text(path.read_text().replace(digest, "not-a-hash"))
        self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")

    def test_invalid_asset_metadata_is_not_approved(self):
        folder = self.make_packet()
        self.register_asset()
        manifest = folder / "ASSETS.md"
        manifest.write_text(manifest.read_text().replace("- Type: image/png", "- Type: image/jpeg"))
        self.assert_fail_closed(self.approve)

    def test_image_signature_without_valid_container_is_rejected(self):
        folder = self.make_packet()
        source = self.folder / "fake.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-container")
        self.assert_fail_closed(ach.task_add_asset, self.repo, self.project, "task-1", source,
                                origin="synthetic", approved_by="demo-user")
        self.assertEqual([], list((folder / "assets").iterdir()))

    def test_feedback_path_traversal_cannot_append_to_external_record(self):
        external = self.folder / "outside"
        external.mkdir()
        record = external / "UAT_FEEDBACK.md"
        original = b"## Status history\n- 2026-01-01T00:00:00+00:00 | reported | user | report\n"
        record.write_bytes(original)
        for feedback in ("../../../../outside", str(external)):
            with self.subTest(feedback=feedback):
                self.assert_fail_closed(ach.uat_status, self.repo, self.project, feedback,
                                        status="fixed", by="codex", note="fixed", related_pr="")
                self.assertEqual(original, record.read_bytes())

    def test_symlink_task_parent_cannot_create_external_packet(self):
        external = self.folder / "outside"
        external.mkdir()
        (self.repo / "projects/demo/tasks").symlink_to(external, target_is_directory=True)
        self.assert_fail_closed(self.make_packet)
        self.assertEqual([], list(external.iterdir()))

    def test_symlink_asset_directory_cannot_receive_external_write(self):
        folder = self.make_packet()
        external = self.folder / "outside"
        external.mkdir()
        (folder / "assets").rmdir()
        (folder / "assets").symlink_to(external, target_is_directory=True)
        self.assert_fail_closed(self.register_asset)
        self.assertEqual([], list(external.iterdir()))

    def test_uat_screenshot_hash_is_checked_before_publish(self):
        shot = self.folder / "shot.png"
        shot.write_bytes(png_bytes())
        folder = self.report(shot)
        (folder / "assets/shot.png").write_bytes(png_bytes(pad=4))
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, folder.name)

    def test_uat_unregistered_screenshot_is_rejected(self):
        folder = self.report()
        (folder / "assets/unregistered.png").write_bytes(png_bytes())
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, folder.name)

    def test_uat_read_rechecks_screenshot_hash(self):
        shot = self.folder / "shot.png"
        shot.write_bytes(png_bytes())
        folder = self.report(shot)
        ach.uat_publish(self.repo, self.project, folder.name)
        (folder / "assets/shot.png").write_bytes(png_bytes(pad=4))
        with self.assertRaises(ach.HubError):
            ach.uat_read(self.repo, self.project, folder.name, do_sync=False)

    def test_uat_intermediate_rewrite_cannot_be_hidden_by_restoring_tip(self):
        folder = self.report()
        ach.uat_publish(self.repo, self.project, folder.name)
        record = folder / "UAT_FEEDBACK.md"
        original = record.read_bytes()
        record.write_text(record.read_text().replace("Failure", "Rewritten evidence"))
        self.commit("rewrite evidence")
        record.write_bytes(original)
        ach.uat_status(self.repo, self.project, folder.name, status="reproduced", by="codex",
                       note="reproduced", related_pr="")
        self.commit("hide rewrite in final tip")
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, folder.name)

    def test_uat_append_cannot_shadow_original_fields(self):
        folder = self.report()
        ach.uat_publish(self.repo, self.project, folder.name)
        record = folder / "UAT_FEEDBACK.md"
        record.write_text(record.read_text() + "\n## Replacement\n- Source repo: other-repo\n")
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, folder.name)

    def test_status_note_cannot_inject_another_section(self):
        folder = self.report()
        original = (folder / "UAT_FEEDBACK.md").read_bytes()
        self.assert_fail_closed(ach.uat_status, self.repo, self.project, folder.name,
                                status="fixed", by="codex", note="fixed\n## Replacement",
                                related_pr="")
        self.assertEqual(original, (folder / "UAT_FEEDBACK.md").read_bytes())

    def test_uat_status_cannot_skip_required_transitions(self):
        folder = self.report()
        self.assert_fail_closed(ach.uat_status, self.repo, self.project, folder.name,
                                status="re-tested", by="demo-user", note="claimed pass",
                                related_pr="")

    def test_local_workflow_lock_prevents_a_lost_uat_status_update(self):
        folder = self.report()
        original = (folder / "UAT_FEEDBACK.md").read_bytes()
        with ach.sync_lock(self.repo):
            self.assert_fail_closed(ach.uat_status, self.repo, self.project, folder.name,
                                    status="reproduced", by="demo-user", note="race",
                                    related_pr="")
        self.assertEqual(original, (folder / "UAT_FEEDBACK.md").read_bytes())

    def test_manual_status_append_cannot_bypass_transition_rules(self):
        folder = self.report()
        record = folder / "UAT_FEEDBACK.md"
        record.write_text(record.read_text() +
                          "- 2026-01-01T00:00:00+00:00 | re-tested | demo-user | forged\n")
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, folder.name)

    def test_naive_uat_timestamp_fails_closed_instead_of_crashing_validation(self):
        folder = self.report()
        record = folder / "UAT_FEEDBACK.md"
        record.write_text(record.read_text() +
                          "- 2026-01-01T00:00:00 | reproduced | demo-user | forged\n")
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, folder.name)

    def test_read_access_does_not_prove_current_push_permission(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = ach.onboard_check(self.repo, source_repo=str(self.remote))
        self.assertEqual(1, result, buffer.getvalue())
        self.assertIn("UNKNOWN", buffer.getvalue())

    def test_live_push_probe_without_identity_returns_blocked(self):
        self.git(self.repo, "config", "--unset", "user.name")
        self.git(self.repo, "config", "--unset", "user.email")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = ach.onboard_check(self.repo, source_repo=str(self.remote), prove_push=True)
        self.assertEqual(1, result, buffer.getvalue())
        self.assertIn("GIT_IDENTITY", buffer.getvalue())
        self.assertIn("BLOCKED", buffer.getvalue())

    def test_probe_readback_failure_still_cleans_up_and_returns_blocked(self):
        original = ach.run_git

        def intercept(root, *args, **kwargs):
            if args[0] == "ls-remote":
                raise ach.HubError("simulated readback network failure")
            return original(root, *args, **kwargs)

        with mock.patch.object(ach, "run_git", side_effect=intercept):
            ok, detail = ach.probe_push(self.repo, "main")
        self.assertFalse(ok)
        self.assertIn("readback", detail)
        self.assertEqual("", self.git(self.remote, "for-each-ref", "--format=%(refname)",
                                      "refs/ach-onboard/"))

    def test_passed_handoff_must_match_the_retested_source_and_commit(self):
        folder = self.report()
        for status in ("reproduced", "fixed", "re-tested"):
            ach.uat_status(self.repo, self.project, folder.name, status=status, by="demo-user",
                           note=status, related_pr="")
        for source, code in ((SOURCE, "b" * 40), ("https://example.invalid/other.git", CODE)):
            with self.subTest(source=source, code=code):
                self.assert_fail_closed(
                    ach.write_handoff, self.repo, self.project, "codex", "Review", "done",
                    "tests run", "", "review", "VERIFIED", source_repo=source,
                    branch="feature", code_sha=code, pr="NOT_OPENED", build="run tests",
                    tests="passed", acceptance="PASSED", uat=folder.name)

    def test_implementation_handoff_requires_build_and_test_evidence(self):
        self.assert_fail_closed(
            ach.write_handoff, self.repo, self.project, "codex", "Review", "done",
            "", "", "review", "VERIFIED", source_repo=SOURCE, branch="feature",
            code_sha=CODE, pr="NOT_OPENED", acceptance="PENDING")

    def test_task_failed_push_retries_the_same_commit(self):
        self.make_packet()
        self.approve()
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        pending = self.git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(self.baseline, pending)
        hook.write_text("#!/bin/sh\nexit 0\n")
        ach.task_publish(self.repo, self.project, "task-1")
        self.assertEqual(pending, self.remote_head())

    def test_uat_failed_status_push_preserves_evidence_and_recovers(self):
        folder = self.report()
        ach.uat_publish(self.repo, self.project, folder.name)
        original = (folder / "UAT_FEEDBACK.md").read_bytes()
        ach.uat_status(self.repo, self.project, folder.name, status="reproduced", by="codex",
                       note="reproduced", related_pr="")
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assert_fail_closed(ach.uat_publish, self.repo, self.project, folder.name)
        pending = self.git(self.repo, "rev-parse", "HEAD")
        self.assertTrue((folder / "UAT_FEEDBACK.md").read_bytes().startswith(original))
        hook.write_text("#!/bin/sh\nexit 0\n")
        ach.uat_publish(self.repo, self.project, folder.name)
        self.assertEqual(pending, self.remote_head())

    def test_concurrent_uat_updates_fail_closed_without_losing_local_evidence(self):
        folder = self.report()
        ach.uat_publish(self.repo, self.project, folder.name)
        other = self.clone("other")
        other_record = other / folder.relative_to(self.repo) / "UAT_FEEDBACK.md"
        ach.uat_status(other, self.project, folder.name, status="reproduced", by="agent-b",
                       note="independent reproduction", related_pr="")
        expected_local = other_record.read_bytes()
        ach.uat_status(self.repo, self.project, folder.name, status="reproduced", by="agent-a",
                       note="first reproduction", related_pr="")
        ach.uat_publish(self.repo, self.project, folder.name)
        remote_after_first = self.remote_head()
        with self.assertRaises(ach.HubError):
            ach.uat_publish(other, self.project, folder.name)
        self.assertEqual(expected_local, other_record.read_bytes())
        self.assertEqual(remote_after_first, self.remote_head())
        self.assertEqual("", self.git(other, "diff", "--cached", "--name-only"))


if __name__ == "__main__":
    import unittest
    unittest.main()
