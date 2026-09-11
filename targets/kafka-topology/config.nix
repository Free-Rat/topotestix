{ lib, ... }:

{
  # Complete manifests are atomic choices shared by all nodes of a role.
  environment.etc."topotestix-kafka-placement.json".text = [
    ''{"profile":"spread","replicas":[1,3,5],"failed_rack":"rack-a"}''
    ''{"profile":"concentrated","replicas":[1,2,3],"failed_rack":"rack-a"}''
  ];

  environment.etc."topotestix-kafka-intervention".text = [
    "no-fault"
    "leader-kill"
    "rack-kill"
  ];
}
