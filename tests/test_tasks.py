"""v0.2 P0: approved task packets, asset handoff and guarded publication."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "src"))

import ach  # noqa: E402
import support  # noqa: E402
from support import HubFixture, png_bytes  # noqa: E402


class TaskPacketTests(HubFixture):
    # -- happy path -------------------------------------------------------
    def test_approved_packet_and_asset_are_readable_from_a_fresh_clone(self):
        self.make_packet()
        self.register_asset()
        self.approve()
        self.assertEqual(0, ach.validate(self.repo, self.project))
        ach.task_publish(self.repo, self.project, "task-1")
        self.assertNotEqual(self.baseline, self.remote_head())

        verifier = self.clone("verifier")
        prefix = "projects/demo/tasks/task-1"
        for name in ("BRIEF.md", "ACCEPTANCE.md", "ASSETS.md", "APPROVAL.md",
                     "assets/shot-01.png"):
            self.assertTrue((verifier / prefix / name).is_file(), name)
        # The manifest hash in the clone must match the bytes in the clone.
        manifest = ach.parse_assets((verifier / prefix / "ASSETS.md").read_text())
        digest = ach.sha256_file(verifier / prefix / "assets/shot-01.png")
        self.assertEqual(digest, manifest["assets/shot-01.png"]["SHA-256"])
        report = ach.task_read(verifier, self.project, "task-1", do_sync=False)
        self.assertIn("PASS: manifest, approval binding and secrets all verified.", report)
        self.assertIn("Approved by: demo-user", report)

    def test_packet_starts_as_draft_and_validate_accepts_it(self):
        self.make_packet()
        report = ach.task_read(self.repo, self.project, "task-1", do_sync=False)
        self.assertIn("Not approved. Publication is not allowed.", report)
        self.assertIn("PASS: manifest, approval binding and secrets all verified.", report)
        self.assertEqual(0, ach.validate(self.repo, self.project))

    def test_repeated_publish_does_not_duplicate_or_overwrite(self):
        self.make_packet()
        self.approve()
        ach.task_publish(self.repo, self.project, "task-1")
        first = self.remote_head()
        commits = self.git(self.remote, "rev-list", "--count", "main")
        ach.task_publish(self.repo, self.project, "task-1")
        self.assertEqual(first, self.remote_head())
        self.assertEqual(commits, self.git(self.remote, "rev-list", "--count", "main"))

    def test_task_new_refuses_to_reuse_an_existing_id(self):
        self.make_packet()
        message = self.assert_fail_closed(self.make_packet)
        self.assertIn("already exists", message)

    def test_a_published_packet_can_never_be_silently_changed(self):
        self.make_packet()
        self.approve()
        ach.task_publish(self.repo, self.project, "task-1")
        published = self.git(self.remote, "rev-parse", "main")
        # ACCEPTANCE.md is not hash-bound to the approval record, so this reaches the
        # remote comparison guard rather than the approval check.
        acceptance = self.repo / "projects/demo/tasks/task-1/ACCEPTANCE.md"
        acceptance.write_text(acceptance.read_text() + "\n- [ ] AC-9: added after publication.\n")
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("create a NEW task id or revision", message)
        self.assertEqual(published, self.remote_head())

    def test_unregistered_extra_file_in_packet_is_refused(self):
        self.make_packet()
        self.approve()
        (self.repo / "projects/demo/tasks/task-1/notes.txt").write_text("unapproved note")
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("Unrelated or modified files", message)

    # -- approval gate ----------------------------------------------------
    def test_publish_requires_a_human_approval_record(self):
        self.make_packet()
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("not publishable", message)
        self.assertTrue((self.repo / "projects/demo/tasks/task-1/BRIEF.md").is_file())

    def test_approval_cannot_be_repeated_or_forged(self):
        self.make_packet()
        self.approve()
        message = self.assert_fail_closed(self.approve)
        self.assertIn("never re-approved", message)

    def test_brief_edited_after_approval_breaks_the_binding(self):
        self.make_packet()
        self.approve()
        brief = self.repo / "projects/demo/tasks/task-1/BRIEF.md"
        brief.write_text(brief.read_text().replace("Change the demo landing page copy.",
                                                   "Silently widened scope.", 1))
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("no longer binds the brief", message)

    def test_approve_requires_a_named_human_and_a_statement(self):
        self.make_packet()
        message = self.assert_fail_closed(ach.task_approve, self.repo, self.project, "task-1",
                                          approved_by="", statement="approved")
        self.assertIn("--approved-by", message)
        self.assert_fail_closed(ach.task_approve, self.repo, self.project, "task-1",
                                approved_by="demo-user", statement="")

    # -- asset handoff ----------------------------------------------------
    def test_missing_asset_file_fails_closed_and_preserves_the_packet(self):
        self.make_packet()
        self.register_asset()
        self.approve()
        (self.repo / "projects/demo/tasks/task-1/assets/shot-01.png").unlink()
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("Missing or unsafe asset", message)
        self.assertTrue((self.repo / "projects/demo/tasks/task-1/BRIEF.md").is_file())

    def test_asset_bytes_changed_after_registration_are_refused(self):
        self.make_packet()
        self.register_asset()
        self.approve()
        (self.repo / "projects/demo/tasks/task-1/assets/shot-01.png").write_bytes(
            png_bytes(pad=8))
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("manifest and file disagree", message)

    def test_oversized_asset_is_refused(self):
        oversized = png_bytes(pad=ach.MAX_ASSET)
        source = self.folder / "huge.png"
        source.write_bytes(oversized)
        self.make_packet()
        message = self.assert_fail_closed(ach.task_add_asset, self.repo, self.project, "task-1",
                                          source, origin="fixture", approved_by="demo-user")
        self.assertIn("Asset size must be", message)

    def test_non_image_and_spoofed_assets_are_refused(self):
        self.make_packet()
        text = self.folder / "notes.png"
        text.write_text("this is not a png")
        self.assert_fail_closed(ach.task_add_asset, self.repo, self.project, "task-1", text,
                                origin="fixture", approved_by="demo-user")
        binary = self.folder / "payload.exe"
        binary.write_bytes(b"MZ\x90\x00")
        message = self.assert_fail_closed(ach.task_add_asset, self.repo, self.project, "task-1",
                                          binary, origin="fixture", approved_by="demo-user")
        self.assertIn("png/jpeg/gif/webp", message)

    def test_asset_requires_provenance_and_an_approver(self):
        self.make_packet()
        source = self.folder / "shot.png"
        source.write_bytes(png_bytes())
        self.assert_fail_closed(ach.task_add_asset, self.repo, self.project, "task-1", source,
                                origin="", approved_by="demo-user")
        self.assert_fail_closed(ach.task_add_asset, self.repo, self.project, "task-1", source,
                                origin="fixture", approved_by="")

    def test_re_registration_with_different_bytes_never_overwrites(self):
        self.make_packet()
        self.register_asset()
        message = self.assert_fail_closed(
            self.register_asset, payload=png_bytes(pad=4))
        self.assertIn("different hash", message)

    def test_duplicate_registration_with_identical_bytes_is_a_no_op(self):
        self.make_packet()
        first = self.register_asset()
        self.register_asset()
        manifest = ach.parse_assets(
            (self.repo / "projects/demo/tasks/task-1/ASSETS.md").read_text())
        self.assertEqual(1, len(manifest))
        self.assertEqual(ach.sha256_file(first), manifest["assets/shot-01.png"]["SHA-256"])

    # -- path traversal and names ----------------------------------------
    def test_path_helpers_reject_traversal_and_absolute_paths(self):
        for bad in ("../escape", "/etc/passwd", "a/../../b", "projects/x/../y",
                    "", "C:\\windows"):
            self.assertFalse(ach.safe_rel(bad), bad)
        self.assertFalse(ach.is_asset_path("projects/demo/tasks/t1/../assets/a.png"))
        self.assertFalse(ach.is_asset_path("assets/../secret.png"))
        self.assertTrue(ach.is_asset_path("projects/demo/tasks/t1/assets/a.png"))

    def test_path_traversal_slug_is_rejected(self):
        self.assert_fail_closed(ach.task_new, self.repo, self.project, "../escape",
                                title="t", revision="v1", accountable="workbuddy",
                                source_repo="https://example.invalid/app.git", baseline_sha="",
                                scope="s", out_of_scope="", expected="e", request="",
                                evidence="", criteria=[])

    # -- Git preconditions ------------------------------------------------
    def test_missing_git_identity_blocks_publication(self):
        self.make_packet()
        self.approve()
        self.git(self.repo, "config", "user.name", "")
        self.git(self.repo, "config", "user.email", "")
        self.git(self.repo, "config", "user.useConfigOnly", "true")
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("Git identity is unavailable", message)
        self.identity(self.repo)
        ach.task_publish(self.repo, self.project, "task-1")
        self.assertIn("projects/demo/tasks/task-1/BRIEF.md", self.remote_tree())

    def test_unreachable_remote_blocks_publication(self):
        self.make_packet()
        self.approve()
        self.git(self.repo, "remote", "set-url", "origin", str(self.folder / "absent.git"))
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("Git command failed", message)
        self.assertTrue((self.repo / "projects/demo/tasks/task-1/BRIEF.md").is_file())

    def test_existing_local_changes_block_publication(self):
        self.make_packet()
        self.approve()
        (self.repo / "projects/demo/CURRENT_STATUS.md").write_text("changed locally")
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("Tracked local changes", message)

    def test_sync_push_cannot_bypass_the_handoff_only_rule(self):
        self.make_packet()
        self.approve()
        message = self.assert_fail_closed(ach.sync_push, self.repo, self.project)
        self.assertIn("No handoff pushed", message)
        self.assertTrue((self.repo / "projects/demo/tasks/task-1/BRIEF.md").is_file())

    def test_secret_in_brief_blocks_publication(self):
        self.make_packet()
        self.approve()
        brief = self.repo / "projects/demo/tasks/task-1/BRIEF.md"
        brief.write_text(brief.read_text() + "\npassword=supersecret123\n")
        message = self.assert_fail_closed(ach.task_publish, self.repo, self.project, "task-1")
        self.assertIn("credential", message)

    # -- concurrency ------------------------------------------------------
    def test_concurrent_handoff_and_packet_publish_keep_both(self):
        self.make_packet()
        self.approve()
        other = self.clone("other")
        ach.write_handoff(other, self.project, "codex", "Review", "done", "local test",
                          "none", "review", "VERIFIED")
        original = ach.run_git
        fired = False

        def intercept(root, *args, **kwargs):
            nonlocal fired
            if root == self.repo and args and args[0] == "push" and not fired:
                fired = True
                ach.sync_push(other, self.project)
            return original(root, *args, **kwargs)

        with mock.patch.object(ach, "run_git", side_effect=intercept):
            ach.task_publish(self.repo, self.project, "task-1")
        self.assertTrue(fired)
        tree = self.remote_tree()
        self.assertIn("projects/demo/tasks/task-1/BRIEF.md", tree)
        self.assertEqual(1, len([line for line in tree.splitlines()
                                 if line.startswith("projects/demo/handoffs/20")]))


class PublicFixtureTests(unittest.TestCase):
    """The public repository must never carry real project or user material."""

    def git(self, repo, *args) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                              capture_output=True).stdout.strip()

    def test_repository_contains_no_real_project_references(self):
        root = Path(support.ROOT)
        forbidden = ("investment-os", "Investment OS", "deepseek-whale-girl", "xuejh9",
                     "Tauri 2", "沪深300")
        offenders = []
        for path in sorted(root.rglob("*")):
            if ".git" in path.parts or not path.is_file():
                continue
            if path.suffix not in (".md", ".py", ".yml", ".yaml", ".toml", ".txt"):
                continue
            if path.parent.name == "tests" and path.name in ("test_tasks.py", "support.py"):
                continue  # this guard names the strings it forbids
            text = path.read_text(encoding="utf-8", errors="replace")
            offenders.extend(f"{path.relative_to(root)}: {marker}"
                             for marker in forbidden if marker in text)
        self.assertEqual([], offenders)

    def test_private_project_records_are_not_tracked(self):
        root = Path(support.ROOT)
        tracked = self.git(root, "ls-files")
        self.assertEqual([], [line for line in tracked.splitlines()
                              if line.startswith("projects/")])
        self.assertFalse((root / "private-data").exists())


if __name__ == "__main__":
    import unittest
    unittest.main()
