{ lib }:

# v1 property suite: the five basic properties (11 checks) as used by the
# v1 50-seed sweep, before the quota write-burst property was added in v2.

{
  cluster_healthy = {
    name = "etcd-cluster-healthy";
    setup = ''
      def check_etcd_cluster_healthy(machine):
          machine.succeed("etcdctl endpoint health --cluster")
    '';
    check = ''
      _check("etcd-cluster-healthy-from-etcd1", check_etcd_cluster_healthy, etcd1)
      _check("etcd-cluster-healthy-from-etcd2", check_etcd_cluster_healthy, etcd2)
      _check("etcd-cluster-healthy-from-etcd3", check_etcd_cluster_healthy, etcd3)
    '';
  };

  kv_roundtrip = {
    name = "etcd-kv-roundtrip";
    setup = ''
      def check_etcd_kv_roundtrip(writer, reader, key, value):
          writer.succeed(f"etcdctl put {key} {value}")
          reader.succeed(f"etcdctl get {key} | grep '^{value}$'")
    '';
    check = ''
      _check("etcd-kv-roundtrip-etcd1-to-etcd2", check_etcd_kv_roundtrip, etcd1, etcd2, "topotestix-kv-12", "value-12")
      _check("etcd-kv-roundtrip-etcd1-to-etcd3", check_etcd_kv_roundtrip, etcd1, etcd3, "topotestix-kv-13", "value-13")
      _check("etcd-kv-roundtrip-etcd2-to-etcd1", check_etcd_kv_roundtrip, etcd2, etcd1, "topotestix-kv-21", "value-21")
    '';
  };

  leader_is_one_of_three = {
    name = "etcd-leader-is-one-of-three";
    setup = ''
      def check_etcd_single_leader(machine):
          status, out = machine.execute(r"""
      python3 - <<'PY'
      import json
      import subprocess
      import sys

      raw = subprocess.check_output(["etcdctl", "endpoint", "status", "--cluster", "-w", "json"], text=True)
      endpoints = json.loads(raw)
      leaders = [ep for ep in endpoints if ep.get("Status", {}).get("leader") == ep.get("Status", {}).get("header", {}).get("member_id")]
      if len(endpoints) != 3:
          print(f"expected 3 endpoints, got {len(endpoints)}")
          sys.exit(1)
      if len(leaders) != 1:
          print(f"expected exactly one leader, got {len(leaders)}")
          print(raw)
          sys.exit(1)
      PY
          """)
          if status != 0:
              raise AssertionError(out)
    '';
    check = ''
      _check("etcd-single-leader-from-etcd1", check_etcd_single_leader, etcd1)
    '';
  };

  lease_ttl_expiry = {
    name = "etcd-lease-ttl-expiry";
    setup = ''
      def check_etcd_lease_ttl_expiry(machine):
          machine.succeed(r"""
      bash -euo pipefail <<'BASH'
      KEY="topotestix-ttl-key-$(date +%s)-$$"
      LEASE=$(etcdctl lease grant 2 | awk '{print $2}')
      etcdctl put "$KEY" topotestix-ttl-value --lease="$LEASE"
      etcdctl get "$KEY" | grep '^topotestix-ttl-value$'
      for attempt in $(seq 1 10); do
        sleep 1
        if ! etcdctl get "$KEY" | grep -q '^topotestix-ttl-value$'; then
          exit 0
        fi
      done
      echo "TTL key still present after expiry wait"
      etcdctl lease timetolive "$LEASE" || true
      etcdctl get "$KEY" || true
      exit 1
      BASH
          """)
    '';
    check = ''
      _check("etcd-lease-ttl-expiry-etcd1", check_etcd_lease_ttl_expiry, etcd1)
    '';
  };

  service_still_up_after_delay = {
    name = "etcd-still-up-after-delay";
    setup = ''
      def check_etcd_still_up(machine):
          machine.succeed("sleep 20 && systemctl is-active etcd && etcdctl endpoint health --cluster")
    '';
    check = ''
      _check("etcd-still-up-etcd1", check_etcd_still_up, etcd1)
      _check("etcd-still-up-etcd2", check_etcd_still_up, etcd2)
      _check("etcd-still-up-etcd3", check_etcd_still_up, etcd3)
    '';
  };
}
