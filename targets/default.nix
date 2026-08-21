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

  rabbitmq-partition = {
    description = "[prototype] RabbitMQ network-cut exploration";
    topologyTarget = ./rabbitmq-partition/topology.nix;
    configTarget = ./rabbitmq-partition/config.nix;
    baseModule = ./rabbitmq-partition/module.nix;
    testScript = ./rabbitmq-partition/test-script.py;
    properties = ./rabbitmq-partition/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-memory = {
    description = "[prototype] RabbitMQ memory-pressure smoke target";
    topologyTarget = ./rabbitmq-memory/topology.nix;
    configTarget = ./rabbitmq-memory/config.nix;
    baseModule = ./rabbitmq-memory/module.nix;
    testScript = ./rabbitmq-memory/test-script.py;
    properties = ./rabbitmq-memory/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-disk = {
    description = "[thesis] RabbitMQ disk-capacity and confirmation contract";
    topologyTarget = ./rabbitmq-disk/topology.nix;
    configTarget = ./rabbitmq-disk/config.nix;
    baseModule = ./rabbitmq-disk/module.nix;
    testScript = ./rabbitmq-disk/test-script.py;
    properties = ./rabbitmq-disk/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-crash = {
    description = "[thesis candidate] RabbitMQ abrupt broker durability contract";
    topologyTarget = ./rabbitmq-crash/topology.nix;
    configTarget = ./rabbitmq-crash/config.nix;
    baseModule = ./rabbitmq-crash/module.nix;
    testScript = ./rabbitmq-crash/test-script.py;
    properties = ./rabbitmq-crash/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-dns = {
    description = "[prototype] RabbitMQ static host-identity sensitivity target";
    topologyTarget = ./rabbitmq-dns/topology.nix;
    configTarget = ./rabbitmq-dns/config.nix;
    baseModule = ./rabbitmq-dns/module.nix;
    testScript = ./rabbitmq-dns/test-script.py;
    properties = ./rabbitmq-dns/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-dns-contract = {
    description = "RabbitMQ DNS strict formation contract negative control";
    topologyTarget = ./rabbitmq-dns/topology.nix;
    configTarget = ./rabbitmq-dns/config.nix;
    baseModule = ./rabbitmq-dns/module.nix;
    testScript = ./rabbitmq-dns/test-script.py;
    properties = ./rabbitmq-dns-contract/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-disk-availability = {
    description = "RabbitMQ disk-pressure availability boundary negative control";
    topologyTarget = ./rabbitmq-disk/topology.nix;
    configTarget = ./rabbitmq-disk/config.nix;
    baseModule = ./rabbitmq-disk/module.nix;
    testScript = ./rabbitmq-disk/test-script.py;
    properties = ./rabbitmq-disk-availability/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-partition-availability = {
    description = "RabbitMQ quorum partition availability boundary negative control";
    topologyTarget = ./rabbitmq-partition/topology.nix;
    configTarget = ./rabbitmq-partition/config.nix;
    baseModule = ./rabbitmq-partition/module.nix;
    testScript = ./rabbitmq-partition/test-script.py;
    properties = ./rabbitmq-partition-availability/properties.nix;
    reportNode = "rabbit1";
  };

  rabbitmq-failure-domain = {
    description = "[thesis] RabbitMQ replica failure-domain placement contract";
    topologyTarget = ./rabbitmq-failure-domain/topology.nix;
    configTarget = ./rabbitmq-failure-domain/config.nix;
    baseModule = ./rabbitmq-failure-domain/module.nix;
    testScript = ./rabbitmq-failure-domain/test-script.py;
    properties = ./rabbitmq-failure-domain/properties.nix;
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
