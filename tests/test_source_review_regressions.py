"""Independent-review regressions for the v0.3 source publishing boundary.

All repositories and credentials in this module are synthetic local fixtures.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "src"))

import ach  # noqa: E402
from test_source_onboarding import SourceFixture, api, reachable, PRIVATE_URL  # noqa: E402


class SourceReviewRegressionTests(SourceFixture):
    def snapshot_plan(self, project: Path, remote: Path) -> str:
        return ach.source_plan(
            project, "demo", str(remote), self.work,
            authorize="demo-owner", statement="approved synthetic snapshot",
            includes=(), allow_review=(), branch="main", mode="snapshot",
        )[1]

    def test_github_visibility_probe_must_prove_not_public(self):
        project = self.make_git_project()
        self.commit_all(project)
        for status in (0, 403, 429, 500):
            work = self.root / f"work-{status}"
            work.mkdir()
            with self.subTest(status=status):
                with self.assertRaises(ach.HubError) as caught:
                    self.plan(project, PRIVATE_URL, work=work, api_probe=api(status),
                              remote_probe=reachable(True))
                self.assertIn("visibility", str(caught.exception).lower())

    def test_planning_never_overwrites_existing_work_evidence(self):
        project = self.make_git_project()
        self.commit_all(project)
        evidence = self.work / ach.SOURCE_MANIFEST_FILE
        evidence.write_text("preserve me\n", encoding="utf-8")

        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, self.make_remote())

        self.assertIn("never overwritten", str(caught.exception))
        self.assertEqual("preserve me\n", evidence.read_text(encoding="utf-8"))

    def test_publish_rechecks_destination_visibility_after_approval(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        with mock.patch.object(ach, "check_destination",
                               return_value=("refused", "destination became public")):
            with self.assertRaises(ach.HubError) as caught:
                ach.source_publish(self.work, approve_manifest=digest, message="upload")
        self.assertIn("destination became public", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_approved_digest_binds_the_destination(self):
        project = self.make_git_project()
        self.commit_all(project)
        approved_remote = self.make_remote("approved.git")
        substituted_remote = self.make_remote("substituted.git")
        digest = self.plan(project, approved_remote)
        plan = self.work / ach.SOURCE_PLAN_FILE
        plan.write_text(plan.read_text(encoding="utf-8").replace(
            f"- Destination: {approved_remote}", f"- Destination: {substituted_remote}"),
            encoding="utf-8")

        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="upload")

        self.assertIn("does not match", str(caught.exception))
        self.assertEqual([], self.remote_files(approved_remote))
        self.assertEqual([], self.remote_files(substituted_remote))

    def test_approved_digest_binds_the_publication_mode(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        plan = self.work / ach.SOURCE_PLAN_FILE
        plan.write_text(plan.read_text(encoding="utf-8").replace(
            "- Mode: history", "- Mode: snapshot"), encoding="utf-8")

        with self.assertRaises(ach.HubError):
            ach.source_publish(self.work, approve_manifest=digest, message="upload")
        self.assertEqual([], self.remote_files(remote))

    def test_publish_rechecks_destination_again_after_building_the_commit(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        checks = [("local", "available"), ("refused", "destination became public")]
        with mock.patch.object(ach, "check_destination", side_effect=checks):
            with self.assertRaises(ach.HubError) as caught:
                ach.source_publish(self.work, approve_manifest=digest, message="upload")
        self.assertIn("destination became public", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_history_mode_scans_old_blob_contents_not_only_current_files(self):
        project = self.make_git_project(extra_files={
            "config.txt": "api_key=synthetic-secret-value-123456789\n",
        })
        self.commit_all(project, "synthetic credential in history")
        (project / "config.txt").write_text("feature=true\n", encoding="utf-8")
        self.commit_all(project, "remove synthetic credential")
        remote = self.make_remote()

        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, remote)
        self.assertIn("config.txt", str(caught.exception))
        self.assertIn("history", str(caught.exception).lower())

    def test_history_mode_refuses_new_ancestors_after_approval(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        (project / ".env").write_text("api_key=synthetic-secret-value-123456789\n",
                                      encoding="utf-8")
        self.git(project, "add", "-f", ".env")
        self.git(project, "commit", "-q", "-m", "synthetic secret after approval")
        (project / ".env").unlink()
        self.commit_all(project, "remove synthetic secret again")

        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="upload")

        self.assertIn("History changed after approval", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_history_mode_rejects_a_deleted_archive_blob(self):
        project = self.make_git_project(extra_files={"legacy/export.zip": b"PK\x03\x04synthetic"})
        self.commit_all(project, "synthetic archive in history")
        (project / "legacy" / "export.zip").unlink()
        self.commit_all(project, "remove synthetic archive")
        with self.assertRaises(ach.HubError) as caught:
            self.plan(project, self.make_remote())
        self.assertIn("legacy/export.zip", str(caught.exception))

    def test_snapshot_tree_bytes_must_match_manifest_before_push(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.snapshot_plan(project, remote)
        original = ach.snapshot_commit

        def mutate_then_commit(*args, **kwargs):
            (project / "src" / "main.py").write_text(
                "print('changed after approval')\n", encoding="utf-8")
            return original(*args, **kwargs)

        with mock.patch.object(ach, "snapshot_commit", side_effect=mutate_then_commit):
            with self.assertRaises(ach.HubError) as caught:
                ach.source_publish(self.work, approve_manifest=digest, message="snapshot")
        self.assertIn("approved manifest", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_history_tree_bytes_must_match_manifest_before_push(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)
        original = ach.run_git
        changed = False

        def mutate_before_add(root, *args, **kwargs):
            nonlocal changed
            if Path(root).resolve() == project.resolve() and args and args[0] == "add" and not changed \
                    and kwargs.get("env") is None:
                changed = True
                (project / "src" / "main.py").write_text(
                    "print('changed after approval')\n", encoding="utf-8")
            return original(root, *args, **kwargs)

        with mock.patch.object(ach, "run_git", side_effect=mutate_before_add):
            with self.assertRaises(ach.HubError) as caught:
                ach.source_publish(self.work, approve_manifest=digest, message="upload")
        self.assertIn("approved manifest", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_snapshot_failed_push_retry_reuses_the_same_commit(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        hook = remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        digest = self.snapshot_plan(project, remote)

        with self.assertRaises(ach.HubError):
            ach.source_publish(self.work, approve_manifest=digest, message="snapshot")
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        ach.source_publish(self.work, approve_manifest=digest, message="snapshot")

        self.assertEqual("1", self.remote_count(remote))

    def test_failed_snapshot_is_not_an_ancestor_of_a_new_plan(self):
        project = self.make_git_project(extra_files={"remove-before-retry.txt": "synthetic\n"})
        self.commit_all(project)
        remote = self.make_remote()
        hook = remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        first = self.snapshot_plan(project, remote)
        with self.assertRaises(ach.HubError):
            ach.source_publish(self.work, approve_manifest=first, message="rejected snapshot")

        (project / "remove-before-retry.txt").unlink()
        self.commit_all(project, "remove file before newly approved snapshot")
        second_work = self.root / "second-plan"
        second_work.mkdir()
        second = ach.source_plan(
            project, "demo", str(remote), second_work,
            authorize="demo-owner", statement="approved replacement snapshot",
            includes=(), allow_review=(), branch="main", mode="snapshot",
        )[1]
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        ach.source_publish(second_work, approve_manifest=second, message="replacement snapshot")

        self.assertEqual("1", self.remote_count(remote))
        self.assertNotIn("remove-before-retry.txt", self.remote_files(remote))

    def test_repeating_a_successful_snapshot_does_not_create_a_commit(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.snapshot_plan(project, remote)
        ach.source_publish(self.work, approve_manifest=digest, message="snapshot")
        first = self.remote_head(remote)

        ach.source_publish(self.work, approve_manifest=digest, message="snapshot")

        self.assertEqual(first, self.remote_head(remote))
        self.assertEqual("1", self.remote_count(remote))

    def test_snapshot_preserves_all_local_refs_and_reflogs(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        before_refs = self.git(project, "for-each-ref", "--format=%(refname):%(objectname)")
        before_reflog = self.git(project, "reflog", "--all", "--format=%H:%gs")
        digest = self.snapshot_plan(project, remote)

        ach.source_publish(self.work, approve_manifest=digest, message="snapshot")

        self.assertEqual(before_refs,
                         self.git(project, "for-each-ref", "--format=%(refname):%(objectname)"))
        self.assertEqual(before_reflog,
                         self.git(project, "reflog", "--all", "--format=%H:%gs"))

    def test_history_commit_failure_restores_the_original_index(self):
        project = self.make_git_project()
        self.commit_all(project)
        (project / "src" / "main.py").write_text("print('approved edit')\n", encoding="utf-8")
        remote = self.make_remote()
        digest = self.plan(project, remote)
        before_index = self.git(project, "diff", "--cached", "--binary")
        hook = project / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)

        with self.assertRaises(ach.HubError):
            ach.source_publish(self.work, approve_manifest=digest, message="upload")

        self.assertEqual(before_index, self.git(project, "diff", "--cached", "--binary"))
        self.assertEqual([], self.remote_files(remote))

    def test_missing_identity_does_not_initialize_a_plain_project(self):
        project = self.root / "plain-no-identity"
        project.mkdir()
        (project / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
        remote = self.make_remote()
        digest = self.plan(project, remote, branch="main")
        for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                    "GIT_COMMITTER_EMAIL"):
            os.environ.pop(key, None)
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                          "GIT_CONFIG_NOSYSTEM": "1"}, clear=False):
            with self.assertRaises(ach.HubError) as caught:
                ach.source_publish(self.work, approve_manifest=digest, message="upload")

        self.assertIn("Git identity is unavailable", str(caught.exception))
        self.assertFalse((project / ".git").exists())
        self.assertEqual([], self.remote_files(remote))

    def test_history_mode_refuses_to_replace_preexisting_staged_state(self):
        project = self.make_git_project()
        self.commit_all(project)
        (project / "src" / "main.py").write_text("print('staged edit')\n", encoding="utf-8")
        self.git(project, "add", "src/main.py")
        before_index = self.git(project, "diff", "--cached", "--binary")
        remote = self.make_remote()
        digest = self.plan(project, remote)

        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="upload")

        self.assertIn("already has staged changes", str(caught.exception))
        self.assertEqual(before_index, self.git(project, "diff", "--cached", "--binary"))
        self.assertEqual([], self.remote_files(remote))

    def test_history_mode_requires_the_planned_branch_to_be_checked_out(self):
        project = self.make_git_project()
        self.commit_all(project)
        self.git(project, "branch", "release")
        remote = self.make_remote()
        digest = self.plan(project, remote, branch="release")

        with self.assertRaises(ach.HubError) as caught:
            ach.source_publish(self.work, approve_manifest=digest, message="upload")

        self.assertIn("currently on 'main'", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))

    def test_same_project_publications_are_serialized_across_workdirs(self):
        project = self.make_git_project()
        self.commit_all(project)
        remote = self.make_remote()
        digest = self.plan(project, remote)

        with ach.source_publish_lock(project):
            with self.assertRaises(ach.HubError) as caught:
                ach.source_publish(self.work, approve_manifest=digest, message="upload")

        self.assertIn("Another source publication", str(caught.exception))
        self.assertEqual([], self.remote_files(remote))


if __name__ == "__main__":
    import unittest
    unittest.main()
