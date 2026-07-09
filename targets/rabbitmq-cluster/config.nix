{ lib, ... }:

{
  # Baseline target: keep values conservative so every generated variant should
  # form a healthy cluster. Later targets can introduce intentionally tight disk
  # and memory limits.
  virtualisation.memorySize = [ 2048 3072 ];
  virtualisation.diskSize = [ 2048 4096 ];

  services.rabbitmq.configItems = {
    # Keep these values modest for the baseline while still giving the fuzzer a
    # real service-level surface to vary.
    "disk_free_limit.absolute" = [ "50MB" "200MB" ];
    "vm_memory_high_watermark.relative" = [ "0.4" "0.6" ];
    "heartbeat" = [ "30" "60" ];
  };
}
