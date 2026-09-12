{ pkgs, nodeName, ... }:

let
  lib = pkgs.lib;
  # addressSuffix is the test framework's node number (sorted node names:
  # client1 = 1, racka1 = 2, ...); it is the host part on every VLAN. The
  # first broker of each rack is a KRaft voter, the second is broker-only.
  brokerSpecs = {
    racka1 = {
      id = 1;
      addressSuffix = 2;
      rack = "rack-a";
      voter = true;
    };
    racka2 = {
      id = 2;
      addressSuffix = 3;
      rack = "rack-a";
      voter = false;
    };
    rackb1 = {
      id = 3;
      addressSuffix = 4;
      rack = "rack-b";
      voter = true;
    };
    rackb2 = {
      id = 4;
      addressSuffix = 5;
      rack = "rack-b";
      voter = false;
    };
    rackc1 = {
      id = 5;
      addressSuffix = 6;
      rack = "rack-c";
      voter = true;
    };
    rackc2 = {
      id = 6;
      addressSuffix = 7;
      rack = "rack-c";
      voter = false;
    };
  };
  clientVlan = 20;
  isBroker = builtins.hasAttr nodeName brokerSpecs;
  brokerSpec = if isBroker then brokerSpecs.${nodeName} else null;
  isVoter = isBroker && brokerSpec.voter;
  clientAddress =
    if isBroker then "192.168.${toString clientVlan}.${toString brokerSpec.addressSuffix}" else "";
  controllerVoters = lib.concatStringsSep "," (
    lib.mapAttrsToList (name: spec: "${toString spec.id}@${name}-link:9093") (
      lib.filterAttrs (_: spec: spec.voter) brokerSpecs
    )
  );
  # Controller and replication traffic addresses peers by "<node>-link". The
  # JVM resolves those names only through this file, which the test script
  # writes from the VLANs each VM actually has before starting Kafka, so the
  # fuzzed VLAN choice decides which brokers can reach each other.
  linkHostsFile = "/run/topotestix-link-hosts";

  # Brokers expose JMX on the loopback interface only, for the local sampler.
  jmxPort = 9999;
  samplerPath = lib.makeBinPath [
    pkgs.apacheKafka
    pkgs.coreutils
    pkgs.jq
  ];
  # The samplers run inside the VMs, so the test script restores links on
  # schedule whatever a sample is doing. Every tool call is killed after 12 s
  # and recorded with its exit status (137 when killed).
  centralSampler = pkgs.writeShellScriptBin "kafka-rack-links-central-sampler" ''
    export PATH=${samplerPath}:$PATH
    out=$1 stop=$2 bootstrap=$3 topic=$4 period=$5
    config=/etc/topotestix-admin.properties
    work=$(mktemp -d)
    call() {
      name=$1
      tool=$2
      shift 2
      timeout -s KILL 12 "$tool" --command-config "$config" --bootstrap-server "$bootstrap" "$@" \
        >"$work/$name" 2>&1
      echo $? >"$work/$name.status"
    }
    while [ ! -e "$stop" ]; do
      started=$(date +%s%N)
      call topic kafka-topics.sh --describe --topic "$topic" &
      call quorum kafka-metadata-quorum.sh describe --status &
      call replication kafka-metadata-quorum.sh describe --replication &
      wait
      finished=$(date +%s%N)
      jq -cn \
        --argjson started "$started" --argjson finished "$finished" \
        --argjson topic_status "$(cat "$work/topic.status")" \
        --argjson quorum_status "$(cat "$work/quorum.status")" \
        --argjson replication_status "$(cat "$work/replication.status")" \
        --rawfile topic "$work/topic" --rawfile quorum "$work/quorum" \
        --rawfile replication "$work/replication" \
        '{started_wall_ns: $started, finished_wall_ns: $finished, calls: {
          topic: {status: $topic_status, output: $topic[-3000:]},
          quorum: {status: $quorum_status, output: $quorum[-3000:]},
          replication: {status: $replication_status, output: $replication[-3000:]}}}' \
        >>"$out"
      remaining=$(( (started + period * 1000000000 - $(date +%s%N)) / 1000000 ))
      if [ "$remaining" -gt 0 ]; then
        sleep "$(( remaining / 1000 )).$(printf %03d $(( remaining % 1000 )))"
      fi
    done
  '';
  jmxSampler = pkgs.writeShellScriptBin "kafka-rack-links-jmx-sampler" ''
    export PATH=${samplerPath}:$PATH
    out=$1 stop=$2 topic=$3 period=$4
    url=service:jmx:rmi:///jndi/rmi://127.0.0.1:${toString jmxPort}/jmxrmi
    work=$(mktemp -d)
    while [ ! -e "$stop" ]; do
      started=$(date +%s%N)
      timeout -s KILL 12 kafka-jmx.sh --jmx-url "$url" --one-time true --report-format properties \
        --object-name kafka.server:type=raft-metrics \
        --object-name kafka.server:type=broker-metadata-metrics \
        --object-name "kafka.cluster:type=Partition,name=*,topic=$topic,partition=0" \
        --object-name "kafka.server:type=ReplicaManager,name=*" \
        --attributes current-leader,current-epoch,current-state,high-watermark,log-end-offset,last-applied-record-offset,last-applied-record-lag-ms,Value \
        >"$work/jmx" 2>&1
      status=$?
      finished=$(date +%s%N)
      jq -cn \
        --argjson started "$started" --argjson finished "$finished" --argjson status "$status" \
        --rawfile output "$work/jmx" \
        '{started_wall_ns: $started, finished_wall_ns: $finished, status: $status,
          output: $output[-6000:]}' \
        >>"$out"
      remaining=$(( (started + period * 1000000000 - $(date +%s%N)) / 1000000 ))
      if [ "$remaining" -gt 0 ]; then
        sleep "$(( remaining / 1000 )).$(printf %03d $(( remaining % 1000 )))"
      fi
    done
  '';

  workloadClasses =
    pkgs.runCommand "kafka-rack-links-workload-classes"
      {
        nativeBuildInputs = [ pkgs.jdk17_headless ];
      }
      ''
        mkdir -p "$out"
        cp ${./KafkaRackLinksWorkload.java} KafkaRackLinksWorkload.java
        javac -cp "${pkgs.apacheKafka}/libs/*" \
          -d "$out" KafkaRackLinksWorkload.java
      '';
  workload = pkgs.writeShellScriptBin "kafka-rack-links-workload" ''
    exec ${pkgs.apacheKafka.passthru.jre}/bin/java \
      -cp "${workloadClasses}:${pkgs.apacheKafka}/libs/*" \
      KafkaRackLinksWorkload "$@"
  '';
in
{
  virtualisation.memorySize = if isBroker then 1536 else 1024;
  virtualisation.diskSize = if isBroker then 4096 else 2048;
  networking.firewall.enable = false;
  # Keep every VM on its declared VLANs only: otherwise QEMU's user-mode NIC
  # (eth0) receives a DHCP default route.
  networking.useDHCP = false;

  services.apache-kafka = lib.mkIf isBroker {
    enable = true;
    clusterId = "4L6g3nShT-eMCtK--X86sw";
    formatLogDirs = true;
    formatLogDirsIgnoreFormatted = true;
    jvmOptions = [
      "-Xms256m"
      "-Xmx512m"
      "-Djava.net.preferIPv4Stack=true"
      "-Djdk.net.hosts.file=${linkHostsFile}"
      "-Dcom.sun.management.jmxremote.port=${toString jmxPort}"
      "-Dcom.sun.management.jmxremote.rmi.port=${toString jmxPort}"
      "-Dcom.sun.management.jmxremote.host=127.0.0.1"
      "-Dcom.sun.management.jmxremote.authenticate=false"
      "-Dcom.sun.management.jmxremote.ssl=false"
      "-Djava.rmi.server.hostname=127.0.0.1"
    ];
    settings = {
      "node.id" = brokerSpec.id;
      "process.roles" = if isVoter then [ "broker" "controller" ] else [ "broker" ];
      "controller.quorum.voters" = controllerVoters;
      "listeners" =
        lib.optional isVoter "CONTROLLER://0.0.0.0:9093"
        ++ [
          "BROKER://0.0.0.0:9094"
          "CLIENT://${clientAddress}:9095"
        ];
      "advertised.listeners" =
        lib.optional isVoter "CONTROLLER://${nodeName}-link:9093"
        ++ [
          "BROKER://${nodeName}-link:9094"
          "CLIENT://${clientAddress}:9095"
        ];
      "listener.security.protocol.map" = lib.concatStringsSep "," [
        "CONTROLLER:PLAINTEXT"
        "BROKER:PLAINTEXT"
        "CLIENT:PLAINTEXT"
      ];
      "controller.listener.names" = "CONTROLLER";
      "inter.broker.listener.name" = "BROKER";
      "broker.rack" = brokerSpec.rack;
      "log.dirs" = [ "/var/lib/apache-kafka/logs" ];
      "num.partitions" = 1;
      "default.replication.factor" = 3;
      "min.insync.replicas" = 2;
      "offsets.topic.replication.factor" = 3;
      "transaction.state.log.replication.factor" = 3;
      "transaction.state.log.min.isr" = 2;
      "unclean.leader.election.enable" = false;
      "auto.create.topics.enable" = false;
      "group.initial.rebalance.delay.ms" = 0;
    };
  };

  systemd.services.apache-kafka = lib.mkIf isBroker {
    # Started by the test script once the link hosts file exists.
    wantedBy = lib.mkForce [ ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig.Restart = lib.mkForce "no";
  };

  # Bounded client timeouts for every admin tool call made by the harness.
  environment.etc."topotestix-admin.properties".text = ''
    request.timeout.ms=5000
    default.api.timeout.ms=8000
  '';
  environment.etc."topotestix-kafka-package".text = pkgs.apacheKafka.name;
  environment.etc."topotestix-nixpkgs-version".text = lib.version;

  environment.systemPackages = with pkgs; [
    apacheKafka
    apacheKafka.passthru.jre
    centralSampler
    coreutils
    iproute2
    iputils
    jmxSampler
    jq
    workload
  ];
}
