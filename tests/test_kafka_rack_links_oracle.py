import copy
import importlib.util
import os
import unittest

ORACLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "targets",
    "kafka-rack-links",
    "oracle.py",
)
SPEC = importlib.util.spec_from_file_location("kafka_rack_links_oracle", ORACLE_PATH)
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)

TRIANGLE = {"rack-a": [10, 11], "rack-b": [10, 12], "rack-c": [11, 12]}


def rack_vlans(rack_links):
    return {
        node: sorted(rack_links[rack] + [ORACLE.CLIENT_VLAN, ORACLE.RACK_VLANS[rack]])
        for node, rack in ORACLE.RACKS.items()
    }


def valid_result(rack_links=TRIANGLE, cut="10"):
    vlans = rack_vlans(rack_links)
    suffixes = {node: broker_id + 1 for node, broker_id in ORACLE.BROKERS.items()}
    brokers = {}
    for node in ORACLE.BROKERS:
        addresses = {
            peer: ORACLE.link_address(node, peer, vlans, suffixes) for peer in ORACLE.BROKERS
        }
        brokers[node] = {
            "vlans": vlans[node],
            "address_suffix": suffixes[node],
            "link_addresses": addresses,
            "hosts_file": "127.0.0.1 localhost\n"
            + "".join(f"{address} {peer}-link\n" for peer, address in addresses.items()),
            "peer_ping": {
                peer: not address.startswith(ORACLE.UNREACHABLE_PREFIX)
                for peer, address in addresses.items()
                if peer != node
            },
        }
    cut_vlans = ORACLE.parse_cut(cut)
    nics = {
        node: {str(vlan): f"virtio-net-pci.{index}" for index, vlan in enumerate(vlans[node], 1)}
        for node in ORACLE.BROKERS
    }
    baseline = [
        {"op_id": f"run/baseline/{index:04d}", "outcome": "confirmed"} for index in range(100)
    ]
    stream = [{"op_id": f"run/stream/{index:05d}", "outcome": "confirmed"} for index in range(90)]
    stream[20]["outcome"] = "ambiguous"
    return {
        "classification": "completed",
        "error": None,
        "configuration": {"cut": cut, "cut_vlans": cut_vlans},
        "topology": {"brokers": brokers, "links_present": ORACLE.links_present(vlans)},
        "network": {
            "nics": nics,
            "cut_nics": [
                {"node": node, "vlan": vlan, "nic": nics[node][str(vlan)]}
                for node, vlan in ORACLE.expected_cut_nics(cut_vlans, vlans)
            ],
            "cut_started_wall_ns": 1,
            "cut_restored_wall_ns": 2,
        },
        "topic": {
            "pre_cut": {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3, 5]},
            "after": {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3, 5]},
        },
        "workload": {
            "baseline": baseline,
            "stream": stream,
            "recovered": [{"op_id": event["op_id"]} for event in baseline + stream],
            "complete_read": True,
        },
    }


class KafkaRackLinksOracleTests(unittest.TestCase):
    def test_valid_result_passes_every_check(self):
        for rack_links, cut in [
            (TRIANGLE, "10"),
            (TRIANGLE, "none"),
            (TRIANGLE, "10,11,12"),
            ({"rack-a": [10], "rack-b": [10, 12], "rack-c": [12]}, "11"),
        ]:
            result = valid_result(rack_links, cut)
            ORACLE.check_materialized(result)
            ORACLE.check_cut_accurate(result)
            ORACLE.check_confirmed_records_recovered_exactly_once(result)
            ORACLE.check_cluster_recovered(result)

    def test_link_address_uses_rack_network_shared_link_or_no_route(self):
        vlans = rack_vlans({"rack-a": [10], "rack-b": [10, 12], "rack-c": [12]})
        suffixes = {node: broker_id + 1 for node, broker_id in ORACLE.BROKERS.items()}
        self.assertEqual(ORACLE.link_address("racka1", "racka2", vlans, suffixes), "192.168.31.3")
        self.assertEqual(ORACLE.link_address("racka1", "rackb1", vlans, suffixes), "192.168.10.4")
        self.assertEqual(ORACLE.link_address("racka1", "rackc1", vlans, suffixes), "192.0.2.6")
        self.assertEqual(ORACLE.link_address("rackc2", "rackb2", vlans, suffixes), "192.168.12.5")

    def test_link_needs_both_racks(self):
        vlans = rack_vlans({"rack-a": [10], "rack-b": [12], "rack-c": [11]})
        self.assertEqual(ORACLE.links_present(vlans), [])
        vlans = rack_vlans({"rack-a": [10, 11], "rack-b": [10], "rack-c": [12]})
        self.assertEqual(ORACLE.links_present(vlans), [10])

    def test_parse_cut_rejects_unknown_or_repeated_vlans(self):
        self.assertEqual(ORACLE.parse_cut("12,10"), [10, 12])
        for value in ["20", "10,10", "31"]:
            with self.assertRaises(ValueError):
                ORACLE.parse_cut(value)

    def test_materialized_rejects_wrong_hosts_address(self):
        result = valid_result()
        broker = result["topology"]["brokers"]["rackc1"]
        broker["link_addresses"]["racka1"] = "192.168.10.2"
        broker["hosts_file"] = broker["hosts_file"].replace(
            "192.168.11.2 racka1", "192.168.10.2 racka1"
        )
        with self.assertRaisesRegex(AssertionError, "rackc1 resolves racka1"):
            ORACLE.check_materialized(result)

    def test_materialized_rejects_ping_contradicting_links(self):
        result = valid_result({"rack-a": [10], "rack-b": [10, 12], "rack-c": [12]}, "none")
        result["topology"]["brokers"]["racka1"]["peer_ping"]["rackc1"] = True
        with self.assertRaisesRegex(AssertionError, "racka1 -> rackc1 ping=True"):
            ORACLE.check_materialized(result)

    def test_materialized_rejects_link_outside_rack(self):
        result = valid_result()
        for node in ["racka1", "racka2"]:
            result["topology"]["brokers"][node]["vlans"] = [10, 12, 20, 31]
        with self.assertRaisesRegex(AssertionError, "not a non-empty subset"):
            ORACLE.check_materialized(result)

    def test_materialized_rejects_rack_peers_on_different_vlans(self):
        result = valid_result()
        result["topology"]["brokers"]["rackb2"]["vlans"] = [10, 20, 32]
        with self.assertRaisesRegex(AssertionError, "differ from its rack peers"):
            ORACLE.check_materialized(result)

    def test_cut_rejects_missing_or_wrong_nic(self):
        result = valid_result()
        result["network"]["cut_nics"].pop()
        with self.assertRaisesRegex(AssertionError, "cut NICs"):
            ORACLE.check_cut_accurate(result)
        result = valid_result()
        result["network"]["cut_nics"][0]["nic"] = "virtio-net-pci.9"
        with self.assertRaisesRegex(AssertionError, "is not its VLAN"):
            ORACLE.check_cut_accurate(result)

    def test_cut_rejects_missing_restore(self):
        result = valid_result()
        result["network"]["cut_restored_wall_ns"] = None
        with self.assertRaisesRegex(AssertionError, "cut window"):
            ORACLE.check_cut_accurate(result)

    def test_durability_allows_absent_ambiguous_record(self):
        result = valid_result()
        result["workload"]["recovered"] = [
            record
            for record in result["workload"]["recovered"]
            if record["op_id"] != "run/stream/00020"
        ]
        ORACLE.check_confirmed_records_recovered_exactly_once(result)

    def test_durability_rejects_missing_duplicated_or_unknown(self):
        for mutate, message in [
            (lambda recovered: recovered.pop(150), "missing=\\['run/stream/00050'\\]"),
            (
                lambda recovered: recovered.append({"op_id": "run/stream/00010"}),
                "duplicated=\\['run/stream/00010'\\]",
            ),
            (
                lambda recovered: recovered.append({"op_id": "other/0000"}),
                "unknown=\\['other/0000'\\]",
            ),
        ]:
            result = valid_result()
            mutate(result["workload"]["recovered"])
            with self.assertRaisesRegex(AssertionError, message):
                ORACLE.check_confirmed_records_recovered_exactly_once(result)

    def test_durability_rejects_incomplete_read_and_unconfirmed_baseline(self):
        result = valid_result()
        result["workload"]["complete_read"] = False
        with self.assertRaisesRegex(AssertionError, "complete read"):
            ORACLE.check_confirmed_records_recovered_exactly_once(result)
        result = valid_result()
        result["workload"]["baseline"][3]["outcome"] = "ambiguous"
        with self.assertRaisesRegex(AssertionError, "baseline records not confirmed"):
            ORACLE.check_confirmed_records_recovered_exactly_once(result)

    def test_durability_requires_completed_run(self):
        result = valid_result()
        result["classification"] = "inconclusive"
        with self.assertRaisesRegex(AssertionError, "inconclusive"):
            ORACLE.check_confirmed_records_recovered_exactly_once(result)

    def test_recovery_rejects_isr_smaller_than_before_cut(self):
        result = valid_result()
        result["topic"]["after"] = {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3]}
        with self.assertRaisesRegex(AssertionError, "lacks pre-cut ISR"):
            ORACLE.check_cluster_recovered(copy.deepcopy(result))


class KafkaRackLinksHelperTests(unittest.TestCase):
    def test_version_gate(self):
        good = {"versions": {"kafka": "4.2.0", "java": 'openjdk version "17.0.18" 2026-01-20'}}
        ORACLE.check_runtime_versions(good)
        for field, value in [
            ("kafka", "14.2.0"),
            ("kafka", "4.2.1"),
            ("java", 'openjdk version "21.0.17" 2026-10-17'),
        ]:
            result = copy.deepcopy(good)
            result["versions"][field] = value
            with self.assertRaisesRegex(AssertionError, field + "="):
                ORACLE.check_runtime_versions(result)
        with self.assertRaisesRegex(AssertionError, "kafka="):
            ORACLE.check_runtime_versions({"versions": {}})

    def test_parse_jmx_properties(self):
        isr = "kafka.cluster:type=Partition,name=InSyncReplicasCount,topic=t,partition=0:Value"
        output = (
            "Trying to connect to JMX url: service:jmx:rmi:///jndi/rmi://127.0.0.1:9999/jmxrmi\n"
            "time=1789217410665\n"
            "kafka.server:type=raft-metrics:current-leader=1\n"
            f"{isr}=3\n"
        )
        self.assertEqual(
            ORACLE.parse_jmx_properties(output),
            {"kafka.server:type=raft-metrics:current-leader": "1", isr: "3"},
        )

    def test_parse_admin_outputs(self):
        topic = (
            "Topic: t\tTopicId: x\tPartitionCount: 1\n"
            "\tTopic: t\tPartition: 0\tLeader: 3\tReplicas: 1,3,5\tIsr: 3,5"
            "\tElr: 1\tLastKnownElr: \n"
        )
        self.assertEqual(
            ORACLE.parse_topic_description(topic),
            {"leader": 3, "replicas": [1, 3, 5], "isr": [3, 5], "elr": [1]},
        )
        status = "ClusterId: x\nLeaderId: 5\nLeaderEpoch: 2\nHighWatermark: 812\n"
        self.assertEqual(
            ORACLE.parse_quorum_status(status),
            {"leader_id": 5, "leader_epoch": 2, "high_watermark": 812},
        )
        replication = (
            "NodeId  DirectoryId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp"
            "  Status  \n5  abc  812  0  1789  1789  Leader  \n"
            "1  def  700  112  1700  1690  Follower\n"
        )
        rows = ORACLE.parse_quorum_replication(replication)
        self.assertEqual(
            [(row["node"], row["lag"], row["status"]) for row in rows],
            [(5, 0, "Leader"), (1, 112, "Follower")],
        )
        for parser in [
            ORACLE.parse_topic_description,
            ORACLE.parse_quorum_status,
            ORACLE.parse_quorum_replication,
        ]:
            with self.assertRaises(ValueError):
                parser("Error while executing command: timed out")

    def test_sample_phases_and_counters(self):
        second = 1_000_000_000
        phases = {
            "lead": (0, 10 * second),
            "cut": (10 * second, 70 * second),
            "tail": (70 * second, 100 * second),
        }
        self.assertEqual(ORACLE.sample_phase(-1, phases), "outside")
        self.assertEqual(ORACLE.sample_phase(10 * second, phases), "cut")
        self.assertEqual(ORACLE.sample_phase(100 * second, phases), "outside")
        samples = (
            [{"phase": "cut", "successful": True, "killed": False}] * 5
            + [{"phase": "cut", "successful": False, "killed": True}]
            + [{"phase": "tail", "successful": True, "killed": False}]
        )
        counters = ORACLE.sample_counters(samples, phases, 10)
        self.assertEqual(
            counters["cut"], {"planned": 6, "executed": 6, "successful": 5, "killed": 1}
        )
        self.assertEqual(
            counters["tail"], {"planned": 3, "executed": 1, "successful": 1, "killed": 0}
        )
        self.assertEqual(counters["lead"]["executed"], 0)
        # A cut restored a few milliseconds late still plans six 10 s samples.
        late = {"lead": (0, 0), "cut": (0, 60 * second + 5_000_000), "tail": (None, None)}
        self.assertEqual(ORACLE.sample_counters([], late, 10)["cut"]["planned"], 6)
        unfinished = {"lead": (0, 5 * second), "cut": (5 * second, None), "tail": (None, None)}
        self.assertEqual(ORACLE.sample_counters([], unfinished, 10)["cut"]["planned"], 0)
        self.assertEqual(ORACLE.KILLED_STATUS, 137)


if __name__ == "__main__":
    unittest.main()
