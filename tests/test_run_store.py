import os
import tempfile
import unittest

from topotestix.run_store import RunStore


class RunStoreTests(unittest.TestCase):
    def test_create_run_and_list_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            run = store.create_run("kafka-cluster", 4, "smoke")
            store.write_json(
                run["dir"],
                "run.json",
                {"id": run["id"], "target": "kafka-cluster", "seed": 4, "status": "failed"},
            )

            runs = store.list_runs()

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["id"], run["id"])
            self.assertEqual(runs[0]["status"], "failed")

    def test_resolve_run_accepts_unique_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            run = store.create_run("nginx", 1, "smoke")
            store.write_json(run["dir"], "run.json", {"id": run["id"]})

            self.assertEqual(store.resolve_run(run["id"][:12]), run["dir"])
            self.assertTrue(os.path.isdir(store.resolve_run(run["dir"])))


import os
import re
import subprocess
import tempfile
import unittest

from topotestix.run_store import RunStore, git_head, materialize_result_artifacts


class RunStoreArtifactTests(unittest.TestCase):
    def test_materialize_result_artifacts_copies_payload_and_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = os.path.join(tmpdir, "run")
            os.makedirs(run_dir)
            result_dir = os.path.join(tmpdir, "store-out")
            os.makedirs(result_dir)
            with open(os.path.join(result_dir, "report.json"), "w") as f:
                f.write('[{"name": "p", "status": "passed"}]')
            with open(os.path.join(result_dir, "disk-results.json"), "w") as f:
                f.write('{"operations": []}')

            copied = materialize_result_artifacts(result_dir, run_dir)

            self.assertEqual(copied, ["disk-results.json", "report.json"])
            self.assertTrue(os.path.isfile(os.path.join(run_dir, "disk-results.json")))
            self.assertTrue(os.path.isfile(os.path.join(run_dir, "report.json")))

    def test_materialize_result_artifacts_missing_result_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = os.path.join(tmpdir, "run")
            os.makedirs(run_dir)
            missing = os.path.join(tmpdir, "no-such-store-path")
            self.assertEqual(materialize_result_artifacts(missing, run_dir), [])
            self.assertEqual(os.listdir(run_dir), [])

    def test_materialize_result_artifacts_accepts_symlinked_result(self):
        # The orchestrator passes the `result` symlink, not the store path.
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = os.path.join(tmpdir, "run")
            os.makedirs(run_dir)
            result_dir = os.path.join(tmpdir, "store-out")
            os.makedirs(result_dir)
            with open(os.path.join(result_dir, "crash-results.json"), "w") as f:
                f.write("{}")
            os.symlink(result_dir, os.path.join(tmpdir, "result"))

            copied = materialize_result_artifacts(os.path.join(tmpdir, "result"), run_dir)

            self.assertEqual(copied, ["crash-results.json"])
            self.assertTrue(os.path.isfile(os.path.join(run_dir, "crash-results.json")))

    def test_materialize_result_artifacts_preserves_existing_canonical_files(self):
        # The orchestrator writes the canonical report.json before
        # materializing; the read-only 444 store copy of the same name must
        # never overwrite it (or PermissionError), while payloads still copy.
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = os.path.join(tmpdir, "run")
            os.makedirs(run_dir)
            canonical = '["canonical"]'
            with open(os.path.join(run_dir, "report.json"), "w") as f:
                f.write(canonical)
            result_dir = os.path.join(tmpdir, "store-out")
            os.makedirs(result_dir)
            with open(os.path.join(result_dir, "report.json"), "w") as f:
                f.write('["store-copy, 444"]')
            os.chmod(os.path.join(result_dir, "report.json"), 0o444)
            with open(os.path.join(result_dir, "crash-results.json"), "w") as f:
                f.write("{}")

            copied = materialize_result_artifacts(result_dir, run_dir)

            self.assertEqual(copied, ["crash-results.json"])
            with open(os.path.join(run_dir, "report.json")) as f:
                self.assertEqual(f.read(), canonical)


class GitHeadTests(unittest.TestCase):
    def test_git_head_returns_head_sha_for_repo(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        head = git_head(repo_root)
        self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{40}", head))
        expected = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(head, expected)

    def test_git_head_empty_outside_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(git_head(tmpdir), "")


if __name__ == "__main__":
    unittest.main()
