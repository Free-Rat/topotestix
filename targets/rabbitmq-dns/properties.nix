{ lib }:

# Properties for the DNS / hostname target. The test driver installs a
# per-run name-resolution state on every node (valid, missing-seed,
# ambiguous-seed, or all-to-same), attempts cluster formation the way a node
# would at startup, then exercises per-node durable store-and-forward. It
# writes a results document to /tmp/dns-results.json on rabbit1; these
# properties assert which resolution state ACTUALLY materialised.
#
# The core expectation, per the deep-sweep plan's DNS axis, is:
#   * valid configs cluster correctly            -> formation_matches_mode
#   * invalid configs fail cleanly               -> formation_matches_mode
#   * no accidental split cluster from resolver  -> no_phantom_members
#     mismatch                                     + reported_member_count_matches
# and, because the broker must stay internally consistent whatever its peers
# are called, durable delivery round-trips exactly in every mode.
#
# Only each property's `setup` and `check` Python strings are concatenated by
# the runner (see lib/properties.nix); nothing Nix-side other than the
# harness-provided node variables and the standard library is available inside
# them, so every block is self-contained.

{
  # ---------------------------------------------------------------------------
  # Core DNS property: the observed cluster-formation outcome must match the
  # fuzzed resolution mode. In the "valid" state every node must reach the
  # full 3-node cluster (all joins succeed and every node sees all three
  # members). In the broken states (missing-seed, ambiguous-seed, all-to-same)
  # formation must FAIL cleanly — at least one join refused OR some node's
  # membership view is not the canonical set — so a broken resolver never
  # masquerades as a healthy 3-node cluster.
  # ---------------------------------------------------------------------------
  formation_matches_mode = {
    name = "rabbitmq-dns-formation-matches-mode";
    setup = ''
def check_formation_matches_mode():
    """Cluster formation must reflect the resolved name state, exactly.

    valid   -> all joins succeed and every node reports the canonical 3.
    broken  -> the run must NOT look like a healthy full cluster: a join is
               refused or some node's membership view is missing a peer.
    """
    canonical = {"rabbit@rabbit1", "rabbit@rabbit2", "rabbit@rabbit3"}
    raw = rabbit1.succeed("cat /tmp/dns-results.json")
    results = json.loads(raw)
    mode = results["mode"]
    members = results["members"]
    join_ok = results["join_ok"]

    all_joined = all(join_ok.values())
    everyone_sees_all = all(
        set(members[node]) == canonical
        for node in ["rabbit1", "rabbit2", "rabbit3"]
    )
    formed_full = all_joined and everyone_sees_all

    if mode == "valid":
        if not formed_full:
            raise AssertionError(
                "valid DNS did not form a full 3-node cluster: "
                "join_ok=" + str(join_ok)
                + "; members=" + str(members)
            )
    else:
        if formed_full:
            raise AssertionError(
                "broken DNS mode " + mode + " falsely reported as a healthy "
                "full 3-node cluster; a resolver mismatch must not masquerade "
                "as success (join_ok=" + str(join_ok) + ", members="
                + str(members) + ")"
            )
    '';
    check = ''
_check("rabbitmq-dns-formation-matches-mode", check_formation_matches_mode)
    '';
  };

  # ---------------------------------------------------------------------------
  # No accidental split cluster: cluster membership must be symmetric in both
  # directions across every node. If rabbit@rabbitB is in node A's cluster view
  # while node B does not report node A, that is a split-brain / phantom
  # membership induced by the resolver — exactly the "accidental split cluster
  # from name-resolution mismatch" the plan names as the bug to catch.
  # ---------------------------------------------------------------------------
  no_phantom_members = {
    name = "rabbitmq-dns-no-phantom-members";
    setup = ''
def check_no_phantom_members():
    """Membership views must be symmetric between every pair of nodes."""
    raw = rabbit1.succeed("cat /tmp/dns-results.json")
    results = json.loads(raw)
    members = results["members"]

    def base(name):
        # "rabbit@rabbit2" -> "rabbit2"
        return name.split("@", 1)[1] if "@" in name else name

    nodes = ["rabbit1", "rabbit2", "rabbit3"]
    for a in nodes:
        for view_member in members.get(a, []):
            b = base(view_member)
            if b not in nodes:
                continue
            if b == a:
                continue
            # If A claims B is a peer, B must claim A back.
            if "rabbit@" + a not in members.get(b, []):
                raise AssertionError(
                    "asymmetric cluster membership (split cluster) on broken "
                    "resolver: " + a + " reports " + view_member + " as a member"
                    + ", but " + b + " does not report " + a
                    + " (members=" + str(members) + ")"
                )
    '';
    check = ''
_check("rabbitmq-dns-no-phantom-members", check_no_phantom_members)
    '';
  };

  # ---------------------------------------------------------------------------
  # Reported membership count must be consistent with the mode. A healthy
  # cluster reports exactly the canonical three node names from every node. A
  # broken resolver state must not present a full, clean membership set that
  # is indistinguishable from a healthy cluster.
  # ---------------------------------------------------------------------------
  reported_member_count_matches = {
    name = "rabbitmq-dns-reported-member-count";
    setup = ''
def check_reported_member_count_matches():
    """Member counts must agree with whether a full cluster may exist."""
    raw = rabbit1.succeed("cat /tmp/dns-results.json")
    results = json.loads(raw)
    mode = results["mode"]
    members = results["members"]

    canonical = {"rabbit@rabbit1", "rabbit@rabbit2", "rabbit@rabbit3"}
    nodes = ["rabbit1", "rabbit2", "rabbit3"]

    if mode == "valid":
        for node in nodes:
            if set(members.get(node, [])) != canonical:
                raise AssertionError(
                    "valid mode: node " + node + " reports "
                    + str(sorted(members.get(node, [])))
                    + ", expected exactly the canonical 3 (members="
                    + str(members) + ")"
                )
    else:
        # A broken resolver must not make every node report the complete,
        # canonical 3-member cluster (that would be a false healthy state).
        if all(set(members.get(n, [])) == canonical for n in nodes):
            raise AssertionError(
                "broken mode " + mode + ": every node reports the full "
                "canonical 3-member cluster, making the broken resolver "
                "indistinguishable from a healthy cluster (members="
                + str(members) + ")"
            )
    '';
    check = ''
_check("rabbitmq-dns-reported-member-count", check_reported_member_count_matches)
    '';
  };

  # ---------------------------------------------------------------------------
  # Durable delivery: whatever its peers are named, the report node is a valid
  # standalone AMQP broker, and its broker must keep its own durable,
  # confirmed messages internally consistent. The recover count must equal the
  # number of confirmed publishes exactly (no silent loss, no phantom
  # duplicate) in every mode, valid or broken.
  # ---------------------------------------------------------------------------
  durable_delivery = {
    name = "rabbitmq-dns-durable-delivery";
    setup = ''
def check_durable_delivery():
    """Every confirmed durable publish must round-trip exactly, in all modes."""
    raw = rabbit1.succeed("cat /tmp/dns-results.json")
    results = json.loads(raw)
    summary = results["publish_summary"]
    ok = summary["ok"]
    recovered = results["recovered"]
    mode = results["mode"]

    if recovered < 0:
        raise AssertionError(
            "could not parse recovered count from drain output: "
            + str(results.get("recovered"))
        )

    if ok == 0:
        raise AssertionError(
            "no publishes were confirmed on mode " + mode
            + "; the report node broker must stay a valid AMQP endpoint "
            + "(publish_summary=" + str(summary) + ")"
        )

    if recovered < ok:
        raise AssertionError(
            "silent durable message loss on mode " + mode + ": "
            + str(ok) + " confirmed publishes, only " + str(recovered)
            + " retrieved"
        )
    if recovered > ok:
        raise AssertionError(
            "phantom durable messages on mode " + mode + ": "
            + str(ok) + " confirmed publishes, but " + str(recovered)
            + " retrieved"
        )
    '';
    check = ''
_check("rabbitmq-dns-durable-delivery", check_durable_delivery)
    '';
  };

  # ---------------------------------------------------------------------------
  # Service liveness: every node's rabbitmq.service must be active regardless
  # of the resolver state. A broken resolver may prevent joins, but it must
  # not take the local broker down.
  # ---------------------------------------------------------------------------
  service_up_all = {
    name = "rabbitmq-dns-service-up";
    setup = ''
def check_service_up(machine):
    machine.succeed("systemctl is-active rabbitmq.service")
    '';
    check = ''
_check("rabbitmq-dns-service-up-rabbit1", check_service_up, rabbit1)
_check("rabbitmq-dns-service-up-rabbit2", check_service_up, rabbit2)
_check("rabbitmq-dns-service-up-rabbit3", check_service_up, rabbit3)
    '';
  };
}
