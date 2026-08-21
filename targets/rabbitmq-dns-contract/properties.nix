{ lib }:

# Strict negative control for rabbitmq-dns. The canonical DNS target correctly
# accepts broken resolver modes as expected degradation. This paired target
# deliberately keeps the stronger contract "the cluster must form" so broken
# mappings produce an explainable expected_failure.
{
  formation_contract = {
    name = "rabbitmq-dns-strict-formation-contract";
    setup = ''
def check_dns_strict_formation():
    raw = rabbit1.succeed("cat /tmp/dns-results.json")
    results = json.loads(raw)
    canonical = {"rabbit@rabbit1", "rabbit@rabbit2", "rabbit@rabbit3"}
    formed_full = all(joined for joined in results["join_ok"].values()) and all(
        set(results["members"].get(node, [])) == canonical
        for node in ["rabbit1", "rabbit2", "rabbit3"]
    )
    if not formed_full:
        raise AssertionError(
            "strict formation contract violated: mode=" + results["mode"]
            + "; join_ok=" + str(results["join_ok"])
            + "; members=" + str(results["members"])
        )

    '';
    check = ''
_dns_contract_results = json.loads(rabbit1.succeed("cat /tmp/dns-results.json"))
_check_expected(
    "rabbitmq-dns-strict-formation-contract",
    check_dns_strict_formation,
    _dns_contract_results["mode"] != "valid",
)
    '';
  };
}
