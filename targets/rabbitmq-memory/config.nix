{ lib, ... }:

# Fuzzable memory pressure parameters. Each dimension is a separate
# attribute path so the fuzzer resolves them independently and the
# shrinker can reduce each dimension toward index 0 in isolation.
#
# Index 0 of every dimension is the least-pressured value, so shrinking
# toward 0 produces a minimal, still-relevant configuration (the
# control case that mirrors the rabbitmq-cluster baseline).
{
  # Per-node VM memory in MB. Lower values leave less memory for the
  # broker, which forces it into alarm states sooner under publish load.
  # 512 MB is the minimum that lets the broker boot inside the NixOS
  # VM test harness without OOM-killing itself during Erlang startup.
  virtualisation.memorySize = [
    1024
    768
    512
  ];

  # RabbitMQ broker memory alarm watermark (relative to available
  # memory). When the broker exceeds this fraction, it enters the
  # memory-alarm state and blocks new publishes.
  services.rabbitmq.configItems."vm_memory_high_watermark.relative" = [
    "0.5"
    "0.4"
    "0.3"
  ];

  # Number of messages the test driver will publish into the quorum
  # queue. Combined with message_size, this drives the queue backlog
  # size and the broker's working-set pressure.
  environment.etc."topotestix-memory-publish-count".text = [
    "50"
    "500"
    "2000"
  ];

  # Size of each published message in bytes. Larger payloads push the
  # broker toward its watermark faster.
  environment.etc."topotestix-memory-message-size".text = [
    "128"
    "1024"
    "4096"
  ];
}
