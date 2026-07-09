{
  nginx = {
    description = "Single-node nginx smoke target";
    topologyTarget = ./nginx/topology.nix;
    configTarget = ./nginx/config.nix;
    baseModule = ./nginx/module.nix;
    testScript = ./nginx/test-script.py;
    properties = ./nginx/properties.nix;
    reportNode = "machine1";
  };

  kafka = {
    description = "Single-node Kafka KRaft smoke target";
    topologyTarget = ./kafka/topology.nix;
    configTarget = ./kafka/config.nix;
    baseModule = ./kafka/module.nix;
    testScript = ./kafka/test-script.py;
    properties = ./kafka/properties.nix;
    reportNode = "machine1";
  };

  kafka-cluster = {
    description = "Three-node Kafka KRaft cluster smoke target";
    topologyTarget = ./kafka-cluster/topology.nix;
    configTarget = ./kafka-cluster/config.nix;
    baseModule = ./kafka-cluster/module.nix;
    testScript = ./kafka-cluster/test-script.py;
    properties = ./kafka-cluster/properties.nix;
    reportNode = "kafka1";
  };

  etcd-cluster = {
    description = "Three-node etcd Raft cluster target";
    topologyTarget = ./etcd-cluster/topology.nix;
    configTarget = ./etcd-cluster/config.nix;
    baseModule = ./etcd-cluster/module.nix;
    testScript = ./etcd-cluster/test-script.py;
    properties = ./etcd-cluster/properties.nix;
    reportNode = "etcd1";
  };

  rabbitmq-cluster = {
    description = "Three-node RabbitMQ quorum queue baseline target";
    topologyTarget = ./rabbitmq-cluster/topology.nix;
    configTarget = ./rabbitmq-cluster/config.nix;
    baseModule = ./rabbitmq-cluster/module.nix;
    testScript = ./rabbitmq-cluster/test-script.py;
    properties = ./rabbitmq-cluster/properties.nix;
    reportNode = "rabbit1";
  };

  postgresql = {
    description = "Two-node PostgreSQL primary/standby streaming replication target";
    topologyTarget = ./postgresql/topology.nix;
    configTarget = ./postgresql/config.nix;
    baseModule = ./postgresql/module.nix;
    testScript = ./postgresql/test-script.py;
    properties = ./postgresql/properties.nix;
    reportNode = "primary1";
  };
}
