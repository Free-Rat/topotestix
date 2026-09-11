{ pkgs, nodeName, ... }:

let
  lib = pkgs.lib;
  nodeSpecs = {
    kafka1 = {
      id = 1;
      addressSuffix = 2;
      rack = "rack-a";
    };
    kafka2 = {
      id = 2;
      addressSuffix = 3;
      rack = "rack-a";
    };
    kafka3 = {
      id = 3;
      addressSuffix = 4;
      rack = "rack-b";
    };
    kafka4 = {
      id = 4;
      addressSuffix = 5;
      rack = "rack-b";
    };
    kafka5 = {
      id = 5;
      addressSuffix = 6;
      rack = "rack-c";
    };
  };
  isBroker = builtins.hasAttr nodeName nodeSpecs;
  nodeSpec = if isBroker then nodeSpecs.${nodeName} else null;
  internalAddress = if isBroker then "192.168.10.${toString nodeSpec.addressSuffix}" else "";
  externalAddress = if isBroker then "192.168.20.${toString nodeSpec.addressSuffix}" else "";
  controllerVoters = lib.concatStringsSep "," (
    lib.mapAttrsToList (
      _: spec: "${toString spec.id}@192.168.10.${toString spec.addressSuffix}:9093"
    ) nodeSpecs
  );
  workloadClasses =
    pkgs.runCommand "kafka-topology-workload-classes"
      {
        nativeBuildInputs = [ pkgs.jdk17_headless ];
      }
      ''
        mkdir -p "$out"
        cp ${./KafkaTopologyWorkload.java} KafkaTopologyWorkload.java
        javac -cp "${pkgs.apacheKafka}/libs/*" \
          -d "$out" KafkaTopologyWorkload.java
      '';
  workload = pkgs.writeShellScriptBin "kafka-topology-workload" ''
    exec ${pkgs.apacheKafka.passthru.jre}/bin/java \
      -cp "${workloadClasses}:${pkgs.apacheKafka}/libs/*" \
      KafkaTopologyWorkload "$@"
  '';
in
{
  virtualisation.memorySize = if isBroker then 2048 else 1024;
  virtualisation.diskSize = if isBroker then 4096 else 2048;
  networking.firewall.enable = false;

  services.apache-kafka = lib.mkIf isBroker {
    enable = true;
    clusterId = "4L6g3nShT-eMCtK--X86sw";
    formatLogDirs = true;
    formatLogDirsIgnoreFormatted = true;
    jvmOptions = [
      "-Xms256m"
      "-Xmx512m"
      "-Djava.net.preferIPv4Stack=true"
    ];
    settings = {
      "node.id" = nodeSpec.id;
      "process.roles" = [
        "broker"
        "controller"
      ];
      "controller.quorum.voters" = controllerVoters;
      "listeners" = [
        "CLIENT_INTERNAL://${internalAddress}:9092"
        "CONTROLLER://${internalAddress}:9093"
        "BROKER://${internalAddress}:9094"
        "CLIENT_EXTERNAL://${externalAddress}:9095"
      ];
      "advertised.listeners" = [
        "CLIENT_INTERNAL://${internalAddress}:9092"
        "BROKER://${internalAddress}:9094"
        "CLIENT_EXTERNAL://${externalAddress}:9095"
      ];
      "listener.security.protocol.map" = lib.concatStringsSep "," [
        "CLIENT_INTERNAL:PLAINTEXT"
        "CONTROLLER:PLAINTEXT"
        "BROKER:PLAINTEXT"
        "CLIENT_EXTERNAL:PLAINTEXT"
      ];
      "controller.listener.names" = "CONTROLLER";
      "inter.broker.listener.name" = "BROKER";
      "broker.rack" = nodeSpec.rack;
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
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig.Restart = lib.mkForce "no";
  };

  environment.etc."topotestix-kafka-node.json" = lib.mkIf isBroker {
    text = builtins.toJSON {
      inherit nodeName;
      broker_id = nodeSpec.id;
      rack = nodeSpec.rack;
      internal_address = internalAddress;
      external_address = externalAddress;
    };
  };

  environment.etc."topotestix-kafka-package".text = pkgs.apacheKafka.name;
  environment.etc."topotestix-nixpkgs-version".text = lib.version;

  environment.systemPackages = with pkgs; [
    apacheKafka
    apacheKafka.passthru.jre
    coreutils
    iproute2
    jq
    workload
  ];
}
