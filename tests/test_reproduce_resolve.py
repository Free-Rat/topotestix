"""Tests for experiments/reproduce/resolve.py.

Pure parts (hashing/collisions, marginals, pairwise coverage, formatting,
idempotent jsonl append, artifact collection) are tested without nix. One
integration test calls resolve_seed("etcd-cluster", 1, ".") live and is
skipped when nix is unavailable.
"""

import json
import os
import shutil
import tempfile
import unittest
import unittest.mock
from types import SimpleNamespace

from experiments.reproduce.resolve import (
    append_seed_line,
    build_resolution_artifacts,
    collect_existing,
    collision_groups,
    fmt6,
    marginals_rows,
    pairwise_coverage,
    per_seed_path,
    prime_dims,
    recorded_seeds,
    resolved_hash,
    run_fuzz_units,
    seed_line,
    uniqueness_summary,
    value_at,
)


def make_record(seed, topology, config, topology_choices, config_choices):
    return {
        "seed": seed,
        "topology": topology,
        "config": config,
        "topology_choices": topology_choices,
        "config_choices": config_choices,
    }


def fake_record(seed, topo_count, topo_choice, mem, mem_choice):
    topology = {"roles": {"etcd": 3}, "etcdVlans": [1]}
    topology_choices = {".roles.etcd": 0, ".etcdVlans": 0}
    config = {"etcd": {"virtualisation": {"memorySize": mem}, "services": {"etcd": {}}}}
    config_choices = {"etcd": {".virtualisation.memorySize": mem_choice}}
    return make_record(seed, topology, config, topology_choices, config_choices)


class Fmt6Tests(unittest.TestCase):
    def test_floats_formatted_as_strings_before_writing(self):
        self.assertEqual(fmt6(1.0), "1")
        self.assertEqual(fmt6(0.75), "0.75")
        self.assertEqual(fmt6(2.0 / 3.0), "0.666667")
        self.assertEqual(fmt6(0.0), "0")
        self.assertEqual(fmt6(1.0 / 8.0), "0.125")

    def test_value_at_dotted_path(self):
        obj = {"roles": {"etcd": 3}, "etcdVlans": [1]}
        self.assertEqual(value_at(obj, ".roles.etcd"), 3)
        self.assertEqual(value_at(obj, ".etcdVlans"), [1])
        self.assertEqual(value_at({"a": {"b": {"c": 7}}}, ".a.b.c"), 7)


class HashAndCollisionTests(unittest.TestCase):
    def test_identical_resolutions_share_hash(self):
        a = fake_record(1, 3, 0, 1024, 0)
        b = fake_record(2, 3, 0, 1024, 0)
        self.assertEqual(resolved_hash(a), resolved_hash(b))
        self.assertTrue(resolved_hash(a))

    def test_different_resolutions_differ(self):
        a = fake_record(1, 3, 0, 1024, 0)
        b = fake_record(2, 3, 0, 2048, 1)
        self.assertNotEqual(resolved_hash(a), resolved_hash(b))

    def test_collision_groups_only_multi_seed_groups_sorted(self):
        records = [
            fake_record(3, 3, 0, 2048, 1),
            fake_record(1, 3, 0, 1024, 0),
            fake_record(2, 3, 0, 1024, 0),
            fake_record(4, 3, 0, 4096, 1),
        ]
        groups = collision_groups(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["seeds"], [1, 2])
        self.assertEqual(groups[0]["hash"], resolved_hash(fake_record(1, 3, 0, 1024, 0)))

    def test_no_collisions_when_all_unique(self):
        records = [fake_record(s, 3, 0, 1024 * s, 0) for s in (1, 2, 3)]
        self.assertEqual(collision_groups(records), [])


class MarginalsTests(unittest.TestCase):
    def test_tally_from_fake_per_seed_list(self):
        records = [
            fake_record(1, 3, 0, 1024, 0),
            fake_record(2, 3, 0, 1024, 0),
            fake_record(3, 3, 0, 2048, 1),
        ]
        rows = marginals_rows(records)
        by_dim = {}
        for row in rows:
            by_dim.setdefault(row["dimension"], []).append((row["resolved_value"], row["count"]))
        self.assertEqual(by_dim["topology:.roles.etcd"], [("3", 3)])
        self.assertEqual(by_dim["topology:.etcdVlans"], [("[1]", 3)])
        self.assertEqual(
            sorted(by_dim["etcd:.virtualisation.memorySize"]), [("1024", 2), ("2048", 1)]
        )
        # Rows globally sorted by (dimension, value).
        keys = [(r["dimension"], r["resolved_value"]) for r in rows]
        self.assertEqual(keys, sorted(keys))

    def test_marginals_empty_records(self):
        self.assertEqual(marginals_rows([]), [])


class PairwiseCoverageTests(unittest.TestCase):
    def setUp(self):
        # Tiny synthetic target: 2 dims x 2 values -> pairs_total = 4.
        self.dims = {
            "a:.v": {"n": 2, "values": [10, 20]},
            "b:.v": {"n": 2, "values": ["x", "y"]},
        }

    def record(self, a_val, b_val):
        return make_record(
            1,
            {},
            {"a": {"v": a_val}, "b": {"v": b_val}},
            {},
            {"a": {".v": 0}, "b": {".v": 0}},
        )

    def test_full_coverage(self):
        records = [
            self.record(10, "x"),
            self.record(20, "x"),
            self.record(10, "y"),
            self.record(20, "y"),
        ]
        cov = pairwise_coverage(records, self.dims)
        self.assertEqual(cov["pairs_total"], 4)
        self.assertEqual(cov["pairs_covered"], 4)
        self.assertEqual(cov["coverage"], "1")
        self.assertEqual(cov["uncovered_sample"], [])

    def test_partial_coverage(self):
        records = [self.record(10, "x"), self.record(20, "x"), self.record(10, "y")]
        cov = pairwise_coverage(records, self.dims)
        self.assertEqual(cov["pairs_total"], 4)
        self.assertEqual(cov["pairs_covered"], 3)
        self.assertEqual(cov["coverage"], "0.75")
        self.assertEqual(
            cov["uncovered_sample"],
            [{"dim_a": "a:.v", "val_a": "20", "dim_b": "b:.v", "val_b": '"y"'}],
        )

    def test_empty_records_cover_nothing(self):
        cov = pairwise_coverage([], self.dims)
        self.assertEqual(cov["pairs_total"], 4)
        self.assertEqual(cov["pairs_covered"], 0)
        self.assertEqual(cov["coverage"], "0")
        self.assertEqual(len(cov["uncovered_sample"]), 4)


class UniquenessTests(unittest.TestCase):
    def test_summary_fields(self):
        records = [
            fake_record(1, 3, 0, 1024, 0),
            fake_record(2, 3, 0, 1024, 0),
            fake_record(3, 3, 0, 2048, 1),
        ]
        summary = uniqueness_summary("etcd-cluster", 96, records)
        self.assertEqual(summary["target"], "etcd-cluster")
        self.assertEqual(summary["space_size"], 96)
        self.assertEqual(summary["seeds"], 3)
        self.assertEqual(summary["unique_resolved"], 2)
        self.assertEqual(summary["duplicate_rate"], "0.333333")
        self.assertEqual(len(summary["collisions"]), 1)
        self.assertEqual(summary["collisions"][0]["seeds"], [1, 2])

    def test_summary_no_records(self):
        summary = uniqueness_summary("t", 96, [])
        self.assertEqual(summary["seeds"], 0)
        self.assertEqual(summary["unique_resolved"], 0)
        self.assertEqual(summary["duplicate_rate"], "0")
        self.assertEqual(summary["collisions"], [])


class IdempotentAppendTests(unittest.TestCase):
    def test_append_once_then_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "resolution", "etcd-cluster", "per-seed-choices.jsonl")
            record = fake_record(1, 3, 0, 1024, 0)
            self.assertTrue(append_seed_line(path, record))
            self.assertFalse(append_seed_line(path, record))
            self.assertFalse(append_seed_line(path, fake_record(1, 3, 0, 1024, 0)))
            with open(path, "r", encoding="utf-8") as fh:
                lines = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["seed"], 1)
            self.assertEqual(lines[0], json.loads(seed_line(record)))

    def test_distinct_seeds_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "per-seed-choices.jsonl")
            self.assertTrue(append_seed_line(path, fake_record(1, 3, 0, 1024, 0)))
            self.assertTrue(append_seed_line(path, fake_record(2, 3, 0, 2048, 1)))
            with open(path, "r", encoding="utf-8") as fh:
                seeds = [json.loads(line)["seed"] for line in fh if line.strip()]
            self.assertEqual(seeds, [1, 2])


class CollectExistingTests(unittest.TestCase):
    def test_roundtrip_of_written_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tdir = os.path.join(tmp, "resolution", "etcd-cluster")
            os.makedirs(tdir)
            records = [fake_record(1, 3, 0, 1024, 0), fake_record(2, 3, 0, 2048, 1)]
            with open(os.path.join(tdir, "uniqueness.json"), "w", encoding="utf-8") as fh:
                json.dump(
                    uniqueness_summary("etcd-cluster", 96, records), fh, indent=2, sort_keys=True
                )
            with open(os.path.join(tdir, "marginals.csv"), "w", encoding="utf-8", newline="") as fh:
                fh.write("dimension,resolved_value,count\n")
                fh.write('"etcd:.virtualisation.memorySize","1024",1\n')
                fh.write('"etcd:.virtualisation.memorySize","2048",1\n')
            with open(os.path.join(tdir, "pairwise-coverage.json"), "w", encoding="utf-8") as fh:
                json.dump(pairwise_coverage(records, {}), fh, indent=2, sort_keys=True)
            collected = collect_existing(tmp)
            entry = collected["targets"]["etcd-cluster"]
            self.assertEqual(entry["uniqueness"]["unique_resolved"], 2)
            self.assertEqual(entry["uniqueness"]["space_size"], 96)
            self.assertEqual(len(entry["marginals_rows"]), 2)
            self.assertEqual(entry["marginals_rows"][0]["count"], 1)
            self.assertIn("pairs_total", entry["pairwise"])

    def test_missing_resolution_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(collect_existing(tmp), {"targets": {}})


class BuildArtifactsFromExistingTests(unittest.TestCase):
    def test_no_resolution_work_needed_when_all_lines_present(self):
        # All requested seeds already recorded -> artifacts built without
        # resolve_seed (which would need nix). run_fuzz_units idempotence
        # relies on the same jsonl contract; the dim table is primed so no
        # real nix call happens.
        with tempfile.TemporaryDirectory() as tmp:
            tdir = os.path.join(tmp, "resolution", "fake-target")
            os.makedirs(tdir)
            records = [fake_record(1, 3, 0, 1024, 0), fake_record(2, 3, 0, 2048, 1)]
            with open(os.path.join(tdir, "per-seed-choices.jsonl"), "w", encoding="utf-8") as fh:
                for record in records:
                    fh.write(seed_line(record) + "\n")
            prime_dims(
                "fake-target",
                tmp,
                {
                    "topology": {
                        ".roles.etcd": {"n": 1, "values": [3]},
                        ".etcdVlans": {"n": 1, "values": [[1]]},
                    },
                    "config": {".virtualisation.memorySize": {"n": 2, "values": [1024, 2048]}},
                    "roles": ["etcd"],
                },
            )
            result = build_resolution_artifacts(tmp, tmp, ["fake-target"], [1, 2])
            self.assertEqual(result["targets"]["fake-target"]["unique_resolved"], 2)
            self.assertEqual(result["targets"]["fake-target"]["space_size"], 2)
            with open(os.path.join(tdir, "uniqueness.json"), encoding="utf-8") as fh:
                uniqueness = json.load(fh)
            self.assertEqual(uniqueness["seeds"], 2)
            self.assertEqual(uniqueness["unique_resolved"], 2)
            self.assertEqual(uniqueness["duplicate_rate"], "0")
            self.assertEqual(uniqueness["collisions"], [])
            # newline="" so a CRLF terminator is seen, not translated away.
            with open(os.path.join(tdir, "marginals.csv"), encoding="utf-8", newline="") as fh:
                marginals = fh.read()
            self.assertTrue(marginals.startswith("dimension,resolved_value,count\n"))
            self.assertNotIn("\r", marginals)
            self.assertIn("topology:.roles.etcd,3,2", marginals)
            with open(os.path.join(tdir, "pairwise-coverage.json"), encoding="utf-8") as fh:
                cov = json.load(fh)
            self.assertEqual(cov["pairs_total"], 5)
            self.assertEqual(cov["pairs_covered"], 5)


FAKE_DIM_TABLE = {
    "topology": {
        ".roles.etcd": {"n": 1, "values": [3]},
        ".etcdVlans": {"n": 1, "values": [[1]]},
    },
    "config": {".virtualisation.memorySize": {"n": 2, "values": [1024, 2048]}},
    "roles": ["etcd"],
}


def fuzz_unit(target, seed):
    return SimpleNamespace(kind="fuzz_only", target=target, seed=seed)


class RunFuzzUnitsCacheTests(unittest.TestCase):
    def test_existing_jsonl_lines_prevent_reevaluation_without_status_json(self):
        # status.json missing (or stale) must NOT defeat the cache: seeds
        # already recorded in per-seed-choices.jsonl are never re-resolved
        # and never appended twice.
        with tempfile.TemporaryDirectory() as tmp:
            tdir = os.path.join(tmp, "resolution", "fake-target")
            os.makedirs(tdir)
            jsonl = os.path.join(tdir, "per-seed-choices.jsonl")
            with open(jsonl, "w", encoding="utf-8") as fh:
                for record in (fake_record(1, 3, 0, 1024, 0), fake_record(2, 3, 0, 2048, 1)):
                    fh.write(seed_line(record) + "\n")
            prime_dims("fake-target", tmp, FAKE_DIM_TABLE)
            resolved_calls = []

            def fake_resolve(target, seed, project_root):
                resolved_calls.append((target, seed))
                return fake_record(seed, 3, 0, 1024, 0)

            units = [fuzz_unit("fake-target", seed) for seed in (1, 2, 3)]
            with unittest.mock.patch("experiments.reproduce.resolve.resolve_seed", fake_resolve):
                run_fuzz_units(tmp, tmp, units)

            self.assertEqual(resolved_calls, [("fake-target", 3)])
            with open(jsonl, encoding="utf-8") as fh:
                lines = [ln for ln in fh.read().splitlines() if ln]
            self.assertEqual(len(lines), 3)
            self.assertEqual(recorded_seeds(per_seed_path(tmp, "fake-target")), {1, 2, 3})
            status_path = os.path.join(tdir, "status.json")
            self.assertTrue(os.path.exists(status_path))
            with open(status_path, encoding="utf-8") as fh:
                status = json.load(fh)
            self.assertEqual(status, {"state": "done", "seeds": [1, 2, 3]})


@unittest.skipUnless(shutil.which("nix"), "nix not available")
class LiveResolutionTests(unittest.TestCase):
    """Integration: one real nix eval over targets/etcd-cluster (no VM build)."""

    def test_resolve_seed_etcd_cluster(self):
        from experiments.reproduce.resolve import resolve_seed

        record = resolve_seed("etcd-cluster", 1, ".")
        for key in (
            "seed",
            "topology",
            "topology_choices",
            "config",
            "config_choices",
            "space_size",
            "dim_counts",
        ):
            self.assertIn(key, record)
        self.assertEqual(record["seed"], 1)
        self.assertEqual(record["topology"]["roles"]["etcd"], 3)
        memory = record["config"]["etcd"]["virtualisation"]["memorySize"]
        self.assertIn(memory, (1024, 2048))
        self.assertEqual(
            record["config_choices"]["etcd"][".virtualisation.memorySize"],
            [1024, 2048].index(memory),
        )
        self.assertIn(".virtualisation.memorySize", record["config_choices"]["etcd"])
        self.assertEqual(record["space_size"], 96)
        self.assertEqual(record["dim_counts"][".virtualisation.memorySize"], 2)
        self.assertEqual(record["dim_counts"][".etcdVlans"], 1)


class TornSeedLineTest(unittest.TestCase):
    """A crash mid-append leaves a final line without its newline."""

    def test_torn_final_line_is_ignored_then_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t", "per-seed-choices.jsonl")
            first = fake_record(1, 3, 0, 1024, 0)
            second = fake_record(2, 3, 0, 2048, 1)
            self.assertTrue(append_seed_line(path, first))
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(seed_line(second)[:10])
            self.assertEqual(recorded_seeds(path), {1})
            self.assertTrue(append_seed_line(path, second))
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertEqual(text, seed_line(first) + "\n" + seed_line(second) + "\n")
            self.assertEqual(recorded_seeds(path), {1, 2})

    def test_same_seed_different_content_is_not_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t", "per-seed-choices.jsonl")
            first = fake_record(1, 3, 0, 1024, 0)
            other = fake_record(1, 3, 0, 2048, 1)
            self.assertNotEqual(seed_line(first), seed_line(other))
            self.assertTrue(append_seed_line(path, first))
            self.assertFalse(append_seed_line(path, other))
            with open(path, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), seed_line(first) + "\n")


if __name__ == "__main__":
    unittest.main()
