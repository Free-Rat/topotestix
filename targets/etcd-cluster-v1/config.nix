{ lib, ... }:

{
  virtualisation.memorySize = [ 1024 2048 ];
  virtualisation.diskSize = [ 2048 4096 ];

  # v1 timing space: includes the invalid combination
  # heartbeat=250 / election=1000 (etcd requires election >= 5 * heartbeat),
  # which the v1 sweep showed as a startup-only failure class. Values
  # recovered from experiments/etcd-cluster/etcd-cluster-sweep-1-50-20260616-summary.json
  # (the v1 config.nix itself predates the per-SUT consolidation and was never
  # committed; the space below is reconstructed from the retained per-seed
  # resolved configurations of all 50 v1 sweep runs).
  services.etcd.extraConf."HEARTBEAT_INTERVAL" = [ "100" "250" ];
  services.etcd.extraConf."ELECTION_TIMEOUT" = [ "1000" "2500" ];
  services.etcd.extraConf."SNAPSHOT_COUNT" = [ "10000" "100000" ];

  # v1 quota space: only generous quotas (16 MiB / 64 MiB), so failures are
  # startup-only and never quota-related.
  services.etcd.extraConf."QUOTA_BACKEND_BYTES" = [ "16777216" "67108864" ];
}
