{ lib, ... }:

# Abrupt durability contract dimensions. The selected node is resolved from the
# observed quorum-queue leader at runtime, not assumed from its hostname.
{
  environment.etc."topotestix-crash-timing".text = [
    "before_publish"
    "during_publish"
    "after_publish"
  ];

  environment.etc."topotestix-crash-target-role".text = [
    "follower"
    "leader"
  ];

  environment.etc."topotestix-crash-delay".text = [
    "2"
    "10"
  ];

  environment.etc."topotestix-crash-publish-count".text = [
    "20"
    "50"
  ];
}
