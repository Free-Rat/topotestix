{ lib, ... }:

{
  # Experiment manifests. Only the client's copy is read: every role resolves
  # its config from its own seed.

  # Link VLANs cut during the fault window.
  environment.etc."topotestix-kafka-cut".text = [
    "none"
    "10"
    "11"
    "12"
    "10,11"
    "10,12"
    "11,12"
    "10,11,12"
  ];

  # Topic replica assignment; the first replica is the preferred leader.
  # spread: one replica per rack; concentrated: two replicas in rack-a.
  environment.etc."topotestix-kafka-placement.json".text = [
    ''{"profile":"spread","replicas":[1,3,5]}''
    ''{"profile":"concentrated","replicas":[1,2,3]}''
  ];
}
