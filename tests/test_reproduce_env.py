"""Tests for experiments/reproduce/env.py (provenance + lock file)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from experiments.reproduce import env
from experiments.reproduce.models import canonical_json, load_manifest, parse_seeds

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
MANIFEST_PATH = os.path.join(REPO_ROOT, "experiments", "reproduce", "MANIFEST.json")


def _tmpdir():
    return tempfile.TemporaryDirectory()


def _write_manifest(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class CanonicalJsonTest(unittest.TestCase):
    def test_sorted_keys_no_whitespace(self):
        self.assertEqual(canonical_json({"b": 1, "a": 2}), '{"a":2,"b":1}')

    def test_stable_across_insertion_order(self):
        self.assertEqual(
            canonical_json({"x": {"b": 1, "a": 2}}), canonical_json({"x": {"a": 2, "b": 1}})
        )

    def test_ascii_safe(self):
        self.assertEqual(canonical_json({"k": "\u00e4"}), '{"k":"\\u00e4"}')


class ParseSeedsTest(unittest.TestCase):
    def test_range(self):
        self.assertEqual(parse_seeds("1..3"), [1, 2, 3])

    def test_comma_list(self):
        self.assertEqual(parse_seeds("1,3,5"), [1, 3, 5])

    def test_bare_int(self):
        self.assertEqual(parse_seeds(7), [7])
        self.assertEqual(parse_seeds("7"), [7])

    def test_list(self):
        self.assertEqual(parse_seeds([2, 1]), [2, 1])

    def test_none(self):
        self.assertEqual(parse_seeds(None), [])


class LocateRepoTest(unittest.TestCase):
    def test_repo_root_ok(self):
        root = env.locate_repo(REPO_ROOT)
        self.assertEqual(root, Path(REPO_ROOT).resolve())

    def test_non_repo_raises(self):
        with _tmpdir() as tmp:
            with self.assertRaises(ValueError):
                env.locate_repo(tmp)


class GitRevTest(unittest.TestCase):
    def test_real_repo(self):
        info = env.git_rev(REPO_ROOT)
        self.assertIsNotNone(info["rev"])
        self.assertEqual(len(info["rev"]), 40)
        self.assertIsInstance(info["dirty"], bool)
        self.assertIsInstance(info["dirty_files"], list)

    def test_missing_repo(self):
        with _tmpdir() as tmp:
            info = env.git_rev(tmp)
            self.assertIsNone(info["rev"])
            self.assertFalse(info["dirty"])
            self.assertEqual(info["dirty_files"], [])

    def test_dirty_paths_keep_their_first_characters(self):
        """porcelain v1 is "XY path": stripping the line first eats the
        status column's own leading space, so " M .gitignore" came back as
        "gitignore"."""
        porcelain = " M .gitignore\n?? study/\nR  old.py -> new.py\nA  a.txt\n"
        with unittest.mock.patch.object(env, "_git") as fake_git:
            fake_git.side_effect = [
                SimpleNamespace(returncode=0, stdout="a" * 40 + "\n"),
                SimpleNamespace(returncode=0, stdout=porcelain),
            ]
            info = env.git_rev("/anywhere")
        self.assertTrue(info["dirty"])
        self.assertEqual(info["dirty_files"], [".gitignore", "study/", "new.py", "a.txt"])


    def test_campaign_out_dir_does_not_mark_the_tree_dirty(self):
        porcelain = "?? experiments/thesis-evals-01-01-2027/\n M lib/x.nix\n"

        def rev(exclude, status=porcelain):
            with unittest.mock.patch.object(env, "_git") as fake_git:
                fake_git.side_effect = [
                    SimpleNamespace(returncode=0, stdout="a" * 40 + "\n"),
                    SimpleNamespace(returncode=0, stdout=status),
                ]
                return env.git_rev(REPO_ROOT, exclude)

        out = os.path.join(REPO_ROOT, "experiments", "thesis-evals-01-01-2027")
        self.assertEqual(rev(out)["dirty_files"], ["lib/x.nix"])
        self.assertTrue(rev(out)["dirty"])
        only_out = "?? experiments/thesis-evals-01-01-2027/\n"
        self.assertFalse(rev(out, only_out)["dirty"])
        self.assertFalse(rev(out + "/", only_out)["dirty"])
        # a sibling campaign or an out dir outside the repo excludes nothing
        self.assertTrue(rev(out + "-other", only_out)["dirty"])
        self.assertTrue(rev("/nowhere/else", only_out)["dirty"])
        self.assertTrue(rev(None, only_out)["dirty"])


class HostInfoTest(unittest.TestCase):
    def test_fields(self):
        info = env.host_info()
        for key in (
            "hostname",
            "cpu_count",
            "total_ram_bytes",
            "available_ram_bytes",
            "kernel",
            "python",
            "method",
        ):
            self.assertIn(key, info)
        self.assertIn(info["method"], ("psutil", "proc"))
        self.assertGreater(info["total_ram_bytes"], 0)
        self.assertGreaterEqual(info["available_ram_bytes"], 0)


class NixInfoTest(unittest.TestCase):
    def test_fields_present(self):
        info = env.nix_info(REPO_ROOT)
        self.assertIn("version", info)
        self.assertIn("nixpkgs_rev", info)
        self.assertIn("error", info)
        if info["error"] is None:
            self.assertIsNotNone(info["version"])


class ThesisRevTest(unittest.TestCase):
    def test_missing_repo_is_none(self):
        self.assertIsNone(env.thesis_rev(os.path.join(REPO_ROOT, "no-such-dir")))

    def test_rename_reports_new_path(self):
        porcelain = "R  old.tex -> new.tex\n M main.tex\n"
        with unittest.mock.patch.object(env, "_git") as fake_git:
            fake_git.side_effect = [
                SimpleNamespace(returncode=0, stdout="b" * 40 + "\n"),
                SimpleNamespace(returncode=0, stdout=porcelain),
            ]
            info = env.thesis_rev("/anywhere")
        self.assertTrue(info["dirty"])
        self.assertEqual(info["dirty_files"], ["new.tex", "main.tex"])


class LockTest(unittest.TestCase):
    def test_write_and_check_no_drift(self):
        with _tmpdir() as tmp:
            lock = env.write_lock(Path(tmp), REPO_ROOT, MANIFEST_PATH)
            self.assertEqual(lock["manifest_sha256"], lock["provenance"]["manifest"]["sha256"])
            self.assertIn("written_at", lock["provenance"])
            self.assertTrue(os.path.isfile(os.path.join(tmp, "MANIFEST.lock.json")))
            self.assertEqual(env.check_lock(Path(tmp), REPO_ROOT, MANIFEST_PATH), [])

    def test_check_missing_lock(self):
        with _tmpdir() as tmp:
            warnings = env.check_lock(Path(tmp), REPO_ROOT, MANIFEST_PATH)
            self.assertEqual(warnings, ["MANIFEST.lock.json missing — run phase 'lock'"])

    def test_manifest_drift_detected(self):
        path = _write_manifest(
            json.dumps({"entries": [{"id": "a", "kind": "run", "target": "nginx"}]})
        )
        try:
            with _tmpdir() as tmp:
                env.write_lock(Path(tmp), REPO_ROOT, path)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(" ")
                warnings = env.check_lock(Path(tmp), REPO_ROOT, path)
                self.assertTrue(any("sha256 drift" in w for w in warnings))
        finally:
            os.unlink(path)

    def test_manifest_unreadable_warns(self):
        with _tmpdir() as tmp:
            env.write_lock(Path(tmp), REPO_ROOT, MANIFEST_PATH)
            warnings = env.check_lock(Path(tmp), REPO_ROOT, os.path.join(tmp, "gone.json"))
            self.assertTrue(any("unreadable" in w for w in warnings))

    def test_write_is_atomic_no_tmp_leftover(self):
        with _tmpdir() as tmp:
            env.write_lock(Path(tmp), REPO_ROOT, MANIFEST_PATH)
            leftovers = [n for n in os.listdir(tmp) if n.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_disk_free_positive(self):
        with _tmpdir() as tmp:
            self.assertGreater(env.disk_free(tmp), 0)


class CampaignTokenTest(unittest.TestCase):
    def test_mint_auto_is_nix_name_safe_and_unique(self):
        a = env.mint_campaign_token()
        b = env.mint_campaign_token()
        self.assertTrue(a.startswith("c") and "-" in a)
        self.assertRegex(a, r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
        self.assertNotEqual(a, b)  # re-minting always differs

    def test_mint_explicit_validated(self):
        self.assertEqual(env.mint_campaign_token("etcd-test-01"), "etcd-test-01")
        for bad in (".leading-dot", "has space", "semi;colon"):
            with self.assertRaises(ValueError):
                env.mint_campaign_token(bad)

    def test_lock_records_token_and_fresh_token_rewrites_only_it(self):
        with _tmpdir() as tmp:
            lock = env.write_lock(
                Path(tmp), REPO_ROOT, MANIFEST_PATH, campaign_token="c20260904-aaaaaa"
            )
            self.assertEqual(lock["campaign_token"], "c20260904-aaaaaa")
            self.assertEqual(env.read_campaign_token(Path(tmp)), "c20260904-aaaaaa")
            prov_before = json.loads((Path(tmp) / "MANIFEST.lock.json").read_text())["provenance"]

            env.set_campaign_token(Path(tmp), "c20260905-bbbbbb")
            self.assertEqual(env.read_campaign_token(Path(tmp)), "c20260905-bbbbbb")
            prov_after = json.loads((Path(tmp) / "MANIFEST.lock.json").read_text())["provenance"]
            self.assertEqual(prov_before, prov_after)  # provenance untouched
            self.assertEqual(env.check_lock(Path(tmp), REPO_ROOT, MANIFEST_PATH), [])

    def test_read_token_absent_is_none(self):
        with _tmpdir() as tmp:
            self.assertIsNone(env.read_campaign_token(Path(tmp)))
            env.write_lock(Path(tmp), REPO_ROOT, MANIFEST_PATH)  # no token arg
            self.assertIsNone(env.read_campaign_token(Path(tmp)))


class UnitIdCollisionTest(unittest.TestCase):
    def test_inline_manifest_expands_collision_free(self):
        manifest_text = json.dumps(
            {
                "entries": [
                    {
                        "id": "kafka-sweep",
                        "kind": "sweep",
                        "target": "kafka-cluster",
                        "seeds": "1..4",
                        "repetitions": 2,
                        "produces": ["kafka-sweep"],
                    },
                    {
                        "id": "etcd-shrink",
                        "kind": "shrink",
                        "target": "etcd-cluster",
                        "seeds": [3],
                        "produces": ["etcd-v2-shrink"],
                    },
                    {
                        "id": "rmq-cell",
                        "kind": "run",
                        "target": "rabbitmq-disk",
                        "seeds": [1],
                        "choices": {"topology": {}, "config": {}},
                        "produces": ["rabbitmq-disk-cells"],
                    },
                    {"id": "suites", "kind": "test_suites", "produces": ["test-suites"]},
                ]
            }
        )
        path = _write_manifest(manifest_text)
        try:
            manifest = load_manifest(path)
            from experiments.reproduce.models import expand_units

            units = expand_units(manifest, "0" * 40)
            ids = [u.id for u in units]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len(units), 8 + 1 + 1 + 1)  # 4 seeds x 2 reps + shrink + cell + suite
        finally:
            os.unlink(path)

    def test_exhaustive_run_name_has_single_cell_suffix(self):
        manifest_text = json.dumps(
            {
                "entries": [
                    {
                        "id": "etcd-exh",
                        "kind": "exhaustive",
                        "target": "etcd-cluster",
                        "exhaustive_role": "nodes",
                        "exhaustive_dims": [{"path": ".a", "n": 2}, {"path": ".b", "n": 2}],
                        "produces": ["etcd-v2-exhaustive"],
                    }
                ]
            }
        )
        path = _write_manifest(manifest_text)
        try:
            from experiments.reproduce.models import expand_units

            units = expand_units(load_manifest(path), "0" * 40)
            self.assertEqual(len(units), 4)
            for u in units:
                self.assertEqual(u.run_name.count("-cell"), 1)
                self.assertEqual(u.run_name, f"etcd-exh-rep0-cell{u.execution_index:03d}")
            names = [u.run_name for u in units]
            self.assertEqual(len(names), len(set(names)))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
