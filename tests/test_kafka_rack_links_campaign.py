import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest

CAMPAIGN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments",
    "kafka-rack-links",
    "campaign.py",
)
SPEC = importlib.util.spec_from_file_location("kafka_rack_links_campaign", CAMPAIGN_PATH)
CAMPAIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMPAIGN)


def resolved_for(seed):
    cell = CAMPAIGN.resolve_cell(seed)
    node_configs = {"client1": {"virtualisation": {"vlans": [20]}}}
    for rack, links in cell["rack_links"].items():
        for index in (1, 2):
            node = rack.replace("-", "") + str(index)
            vlans = sorted(links + [20, CAMPAIGN.RACK_VLANS[rack]])
            node_configs[node] = {"virtualisation": {"vlans": vlans}}
    placement = {
        "profile": cell["placement"],
        "replicas": CAMPAIGN.PLACEMENT_REPLICAS[cell["placement"]],
    }
    etc = {
        "topotestix-kafka-cut": {"text": cell["cut"]},
        "topotestix-kafka-placement.json": {"text": json.dumps(placement)},
    }
    return {
        "nodeConfigs": node_configs,
        "roleFuzz": {"client": {"result": {"environment": {"etc": etc}}}},
    }


def payload_for(
    seed, classification="completed", violation=False, schema_version=3, recovered=True
):
    cell = CAMPAIGN.resolve_cell(seed)
    resolved = resolved_for(seed)
    brokers = {
        node: {"vlans": config["virtualisation"]["vlans"]}
        for node, config in resolved["nodeConfigs"].items()
        if node != "client1"
    }
    baseline = [
        {"op_id": f"b/{index}", "outcome": "confirmed", "started_wall_ns": 0} for index in range(3)
    ]
    stream = [
        {"op_id": "s/0", "outcome": "confirmed", "started_wall_ns": 50},
        {"op_id": "s/1", "outcome": "ambiguous", "started_wall_ns": 150},
        {"op_id": "s/2", "outcome": "confirmed", "started_wall_ns": 250},
    ]
    recovered_records = [{"op_id": event["op_id"]} for event in baseline + stream]
    if violation:
        recovered_records = [record for record in recovered_records if record["op_id"] != "s/2"]
    return {
        "schema_version": schema_version,
        "classification": classification,
        "error": None if classification == "completed" else "why",
        "configuration": {
            "cut_vlans": CAMPAIGN.parse_cut(cell["cut"]),
            "placement": cell["placement"],
        },
        "topology": {
            "brokers": brokers,
            "links_present": cell["links_present"],
            "unfenced_at_start": [1, 2, 3, 4, 5, 6],
        },
        "network": {"cut_started_wall_ns": 100, "cut_restored_wall_ns": 200},
        "topic": {
            "pre_cut": {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3, 5]},
            "after": {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3, 5]}
            if recovered
            else {"leader": -1, "replicas": [1, 3, 5], "isr": [3]},
        },
        "recovery": {"waited_s": 1.0 if recovered else 180.0},
        "samples": {"central": [], "nodes": {}},
        "sampling": {"counters": {}},
        "log_digest": {},
        "workload": {
            "baseline": baseline,
            "stream": stream,
            "recovered": recovered_records if recovered else [],
            "end_offset": len(recovered_records) if recovered else None,
            "complete_read": recovered,
        },
    }


def report_for(violation=False, gates=None, recovered=True):
    names = gates if gates is not None else CAMPAIGN.GATES
    report = [{"name": name, "status": "passed"} for name in names]
    report.append({"name": CAMPAIGN.RECOVERY, "status": "passed" if recovered else "failed"})
    durability_failed = violation or not recovered
    report.append(
        {"name": CAMPAIGN.DURABILITY, "status": "failed" if durability_failed else "passed"}
    )
    return report


class CampaignFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out_dir = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def entry(self, seed, name, resolved=None, payload=None, report=None, repetition=1):
        run_dir = os.path.join(self.out_dir, "runs", name)
        os.makedirs(run_dir)
        for filename, content in [
            ("resolved.json", resolved),
            ("kafka-rack-links-result.json", payload),
            ("report.json", report),
        ]:
            if content is not None:
                with open(os.path.join(run_dir, filename), "w", encoding="utf-8") as handle:
                    json.dump(content, handle)
        return {
            "seed": seed,
            "repetition": repetition,
            "control": False,
            "key": name,
            "duration_seconds": 1.0,
            "exit_status": 0,
            "run_dir": os.path.join("runs", name),
        }


class ResolutionTests(unittest.TestCase):
    def test_resolution_matches_development_sweep(self):
        # Cells observed in resolved.json of the development sweep.
        expected = {
            1: ({"rack-a": [11], "rack-b": [12], "rack-c": [12]}, "12", "concentrated"),
            4: ({"rack-a": [10, 11], "rack-b": [12], "rack-c": [11, 12]}, "10,12", "spread"),
            28: ({"rack-a": [10, 11], "rack-b": [10, 12], "rack-c": [11, 12]}, "10,12", "spread"),
            29: ({"rack-a": [10, 11], "rack-b": [10, 12], "rack-c": [11, 12]}, "10,11", "spread"),
        }
        for seed, (rack_links, cut, placement) in expected.items():
            cell = CAMPAIGN.resolve_cell(seed)
            self.assertEqual(
                (cell["rack_links"], cell["cut"], cell["placement"]), (rack_links, cut, placement)
            )

    def test_formation_prediction(self):
        cases = [
            ([], "spread", "impossible"),
            ([10], "concentrated", "certain"),
            ([10], "spread", "impossible"),
            ([12], "concentrated", "impossible"),
            ([10, 11, 12], "spread", "certain"),
            ([10, 12], "spread", "election"),
            ([11, 12], "concentrated", "election"),
            ([10, 11], "concentrated", "election"),
        ]
        for links, placement, expected in cases:
            self.assertEqual(CAMPAIGN.predict_formation(links, placement), expected)

    def test_development_range_prediction_counts(self):
        counts = {}
        for seed in range(1, 41):
            formation = CAMPAIGN.resolve_cell(seed)["formation"]
            counts[formation] = counts.get(formation, 0) + 1
        self.assertEqual(counts, {"impossible": 18, "certain": 5, "election": 17})

    def test_cut_effect_and_graph_class(self):
        cell = CAMPAIGN.resolve_cell(29)
        self.assertEqual(cell["links_during_cut"], [12])
        self.assertEqual(cell["graph_class"], "one link")
        self.assertTrue(cell["cut_removes_link"])
        cell = CAMPAIGN.resolve_cell(20)
        self.assertEqual((cell["links_present"], cell["cut"]), ([11, 12], "10"))
        self.assertFalse(cell["cut_removes_link"])
        self.assertEqual(cell["graph_class"], "path")


class ExecutionTests(unittest.TestCase):
    def test_units_are_repetition_major_with_unique_tokens(self):
        principal = list(CAMPAIGN.units([41, 42], 3))
        self.assertEqual(
            [(unit["repetition"], unit["seed"]) for unit in principal],
            [(1, 41), (1, 42), (2, 41), (2, 42), (3, 41), (3, 42)],
        )
        controls = list(CAMPAIGN.units([41], 3, control=True))
        tokens = []
        for unit in principal + controls:
            command = CAMPAIGN.run_command(unit, "/tmp/out", "campaign")
            tokens.append(command[command.index("--repetition-token") + 1])
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_only_controls_force_the_cut(self):
        principal = CAMPAIGN.run_command(next(CAMPAIGN.units([41], 1)), "/tmp/out", "c")
        self.assertNotIn("--config-choices", principal)
        control = CAMPAIGN.run_command(next(CAMPAIGN.units([41], 1, control=True)), "/tmp/out", "c")
        choices = json.loads(control[control.index("--config-choices") + 1])
        self.assertEqual(choices, {"client": {CAMPAIGN.CUT_PATH: CAMPAIGN.CUTS.index("none")}})

    def test_memory_guard(self):
        meminfo = "MemTotal:       31000000 kB\nMemAvailable:    9000000 kB\n"
        self.assertEqual(CAMPAIGN.mem_available_kib(meminfo), 9000000)
        self.assertTrue(CAMPAIGN.memory_allows_start(0, 1))
        self.assertFalse(CAMPAIGN.memory_allows_start(1, 9000000))
        self.assertTrue(CAMPAIGN.memory_allows_start(1, 20000000))

    def run_scheduler(self, available_kib, jobs=2, count=4):
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_run_unit(unit, out_dir, campaign, jobs, available, source):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {
                **unit,
                "key": CAMPAIGN.unit_key(unit),
                "exit_status": 0,
                "duration_seconds": 0.05,
                "run_dir": None,
            }

        originals = (CAMPAIGN.run_unit, CAMPAIGN.mem_available_kib)
        CAMPAIGN.run_unit = fake_run_unit
        CAMPAIGN.mem_available_kib = lambda meminfo=None: available_kib
        try:
            with tempfile.TemporaryDirectory() as out_dir:
                planned = list(CAMPAIGN.units(range(1, count + 1), 1))
                CAMPAIGN.execute_units(
                    planned, out_dir, "c", jobs, {"commit": "c" * 40, "changed": []}
                )
                ledger = CAMPAIGN.read_ledger(os.path.join(out_dir, "ledger.jsonl"))
        finally:
            CAMPAIGN.run_unit, CAMPAIGN.mem_available_kib = originals
        return peak, ledger

    def test_scheduler_runs_at_most_jobs_units(self):
        peak, ledger = self.run_scheduler(available_kib=30 * 1024 * 1024)
        self.assertEqual(peak, 2)
        self.assertEqual(len(ledger), 4)
        self.assertEqual(len({entry["key"] for entry in ledger}), 4)

    def test_scheduler_waits_for_memory_before_a_second_unit(self):
        peak, ledger = self.run_scheduler(available_kib=1024)
        self.assertEqual(peak, 1)
        self.assertEqual(len(ledger), 4)


class ClassificationTests(CampaignFixture):
    def test_missing_payload(self):
        row = CAMPAIGN.classify(self.entry(28, "a", resolved=resolved_for(28)), self.out_dir)
        self.assertEqual(row["outcome"], "infrastructure_or_harness_failure")
        self.assertIsNone(row["formed"])

    def test_precondition_failure_is_not_formed(self):
        entry = self.entry(
            28, "a", resolved_for(28), payload_for(28, "precondition_failure"), report_for()
        )
        row = CAMPAIGN.classify(entry, self.out_dir)
        self.assertEqual((row["outcome"], row["formed"]), ("precondition_failure", False))

    def test_materialized_vlans_must_match_resolution(self):
        payload = payload_for(28)
        payload["topology"]["brokers"]["racka1"]["vlans"] = [10, 20, 31]
        entry = self.entry(28, "a", resolved_for(28), payload, report_for())
        self.assertEqual(CAMPAIGN.classify(entry, self.out_dir)["outcome"], "harness_failure")

    def test_every_gate_is_required(self):
        for index, gate in enumerate(CAMPAIGN.GATES):
            gates = [name for name in CAMPAIGN.GATES if name != gate]
            entry = self.entry(
                28, f"g{index}", resolved_for(28), payload_for(28), report_for(gates=gates)
            )
            row = CAMPAIGN.classify(entry, self.out_dir)
            self.assertEqual(row["outcome"], "harness_failure")
            self.assertIn(gate, row["detail"])
        self.assertIn("kafka-rack-links-runtime-versions-pinned", CAMPAIGN.GATES)
        self.assertNotIn(CAMPAIGN.RECOVERY, CAMPAIGN.GATES)

    def test_older_payload_schema_is_not_scored(self):
        for index, version in enumerate([1, 2, None]):
            entry = self.entry(
                28,
                f"s{index}",
                resolved_for(28),
                payload_for(28, schema_version=version),
                report_for(),
            )
            row = CAMPAIGN.classify(entry, self.out_dir)
            self.assertEqual(row["outcome"], "harness_failure")
            self.assertIn("schema_version", row["detail"])

    def test_no_recovery_is_a_recovery_contract_violation(self):
        entry = self.entry(
            28, "a", resolved_for(28), payload_for(28, recovered=False), report_for(recovered=False)
        )
        row = CAMPAIGN.classify(entry, self.out_dir)
        self.assertEqual(row["outcome"], "contract_violation")
        # Without a complete read durability is not judged, so only recovery is violated.
        self.assertEqual(row["violated_contracts"], ["recovery"])
        self.assertEqual(row["signature"]["kinds"], ["not_recovered", "unreadable"])
        self.assertIn("contract_violation (recovery)", CAMPAIGN.execution_line(row))

    def test_recovered_but_unreadable_partition(self):
        payload = payload_for(28)
        payload["workload"].update(complete_read=False, recovered=[])
        report = report_for()
        for item in report:
            if item["name"] in (CAMPAIGN.RECOVERY, CAMPAIGN.DURABILITY):
                item["status"] = "failed"
        row = CAMPAIGN.classify(
            self.entry(28, "a", resolved_for(28), payload, report), self.out_dir
        )
        self.assertEqual(row["violated_contracts"], ["recovery"])
        self.assertEqual(row["signature"]["kinds"], ["unreadable"])

    def test_recovered_with_lost_records_violates_durability_only(self):
        entry = self.entry(
            28, "a", resolved_for(28), payload_for(28, violation=True), report_for(violation=True)
        )
        row = CAMPAIGN.classify(entry, self.out_dir)
        self.assertEqual(row["violated_contracts"], ["durability"])
        self.assertEqual(row["signature"]["kinds"], ["missing"])

    def test_pass_and_violation_signature(self):
        entry = self.entry(28, "a", resolved_for(28), payload_for(28), report_for())
        row = CAMPAIGN.classify(entry, self.out_dir)
        self.assertEqual(row["outcome"], "pass")
        self.assertTrue(row["resolution_matches_plan"])
        self.assertEqual(row["observations"]["stream"]["during"], {"ambiguous": 1})
        entry = self.entry(
            28, "b", resolved_for(28), payload_for(28, violation=True), report_for(violation=True)
        )
        row = CAMPAIGN.classify(entry, self.out_dir)
        self.assertEqual(row["outcome"], "contract_violation")
        self.assertEqual(
            row["signature"],
            {"links_during_cut": [11], "placement": "spread", "kinds": ["missing"]},
        )


def row(seed, outcome, repetition=1, control=False, signature=None, formed=True):
    return {
        "seed": seed,
        "repetition": repetition,
        "control": control,
        "outcome": outcome,
        "formed": formed,
        "signature": signature,
        "resolution_matches_plan": True,
        "checks": {"kafka-rack-links-materialized": "passed"},
    }


class AggregationTests(unittest.TestCase):
    def test_thresholds_count_seeds_not_executions(self):
        rows = [row(28, "pass", repetition) for repetition in (1, 2, 3)]
        summaries = CAMPAIGN.seed_summaries(rows)
        self.assertEqual(len(summaries), 1)
        d2 = CAMPAIGN.evaluate_d2(summaries, rows)
        self.assertEqual(d2["verdict_seeds"], 1)
        self.assertEqual(d2["cut_removes_link_seeds"], [28])
        self.assertFalse(d2["demonstration_minimum_met"])

    def test_prediction_consistency(self):
        # Seed 1 is "impossible": any formed execution breaks the prediction.
        summaries = CAMPAIGN.seed_summaries(
            [row(1, "precondition_failure", 1, formed=False), row(1, "pass", 2)]
        )
        self.assertFalse(summaries[0]["prediction_consistent"])
        self.assertTrue(CAMPAIGN.prediction_consistent("election", False))
        self.assertTrue(CAMPAIGN.prediction_consistent("certain", None))

    def test_confirmatory_rule(self):
        signature = {"links_during_cut": [11], "placement": "spread", "kinds": ["missing"]}
        principal = [
            row(28, "contract_violation", 1, signature=signature),
            row(28, "contract_violation", 2, signature=signature),
            row(28, "pass", 3),
        ]
        controls = [row(28, "pass", index, control=True) for index in (1, 2, 3)]
        result = CAMPAIGN.evaluate_d3(principal + controls)[0]
        self.assertEqual(result["status"], "confirmatory")
        self.assertEqual(result["principal_executions_with_signature"], 2)
        # A control without a verdict leaves the finding exploratory.
        controls[2] = row(28, "inconclusive", 3, control=True)
        self.assertEqual(CAMPAIGN.evaluate_d3(principal + controls)[0]["status"], "exploratory")
        # One principal execution with the signature is exploratory.
        principal[1] = row(28, "pass", 2)
        self.assertEqual(
            CAMPAIGN.evaluate_d3(principal + controls[:2] + [row(28, "pass", 3, control=True)])[0][
                "status"
            ],
            "exploratory",
        )


class ProvenanceTests(unittest.TestCase):
    def test_source_summary_needs_one_clean_recorded_revision(self):
        clean = {"commit": "a" * 40, "dirty": False}
        rows = [{"source": clean}, {"source": dict(clean)}]
        self.assertTrue(CAMPAIGN.source_summary(rows)["single_clean_revision"])
        for extra in [
            {"source": {**clean, "dirty": True}},
            {"source": None},
            {"source": {"commit": "b" * 40, "dirty": False}},
        ]:
            self.assertFalse(CAMPAIGN.source_summary(rows + [extra])["single_clean_revision"])
        self.assertFalse(CAMPAIGN.source_summary([])["single_clean_revision"])

    def test_run_refuses_uncommitted_code_unless_allowed(self):
        original = (CAMPAIGN.source_state, CAMPAIGN.execute_units)
        calls = []
        CAMPAIGN.source_state = lambda: {"commit": "c" * 40, "changed": [" M oracle.py"]}
        CAMPAIGN.execute_units = lambda planned, out_dir, campaign, jobs, source: (
            calls.append((len(planned), source["commit"])) or 0
        )
        try:
            with tempfile.TemporaryDirectory() as out_dir:
                args = argparse.Namespace(
                    out=out_dir,
                    seeds="41-42",
                    repetitions=1,
                    jobs=1,
                    campaign=None,
                    allow_dirty=False,
                )
                self.assertEqual(CAMPAIGN.cmd_run(args), 2)
                self.assertEqual(calls, [])
                args.allow_dirty = True
                self.assertEqual(CAMPAIGN.cmd_run(args), 0)
                self.assertEqual(calls, [(2, "c" * 40)])
        finally:
            CAMPAIGN.source_state, CAMPAIGN.execute_units = original


class ManifestTests(unittest.TestCase):
    def test_manifest_lists_every_run_log_with_its_checksum(self):
        with tempfile.TemporaryDirectory() as out_dir:
            run_dir = os.path.join(out_dir, "runs", "r1")
            os.makedirs(run_dir)
            for name, content in [
                ("stderr.log", b"console"),
                ("racka1-apache-kafka.log", b"journal"),
                ("report.json", b"[]"),
            ]:
                with open(os.path.join(run_dir, name), "wb") as handle:
                    handle.write(content)
            self.assertEqual(CAMPAIGN.write_manifest(out_dir), 2)
            with open(os.path.join(out_dir, "logs-manifest.sha256"), encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            self.assertEqual(
                lines,
                [
                    f"{hashlib.sha256(b'journal').hexdigest()}  runs/r1/racka1-apache-kafka.log",
                    f"{hashlib.sha256(b'console').hexdigest()}  runs/r1/stderr.log",
                ],
            )


if __name__ == "__main__":
    unittest.main()
