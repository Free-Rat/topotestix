{ lib, ... }:

{
  roles.kafka = [ 5 ];
  roles.client = [ 1 ];

  kafkaVlans = [
    [
      10
      20
    ]
  ];

  # Index zero is the shared client plane and is the shrink target.
  clientVlans = [
    [ 10 ]
    [ 20 ]
  ];
}
