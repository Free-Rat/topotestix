{ lib }:

{
  # ---------------------------------------------------------------------------
  # Core durability property: durable, confirmed messages that were accepted
  # by the broker must still be retrievable after the publish load ends and
  # the broker drains. Silent loss under memory pressure is the failure mode
  # this target exists to catch.
  # ---------------------------------------------------------------------------
  no_message_loss = {
    name = "rabbitmq-memory-no-message-loss";
    setup = ''
def check_no_message_loss():
    """Every PUBLISH_OK message must still be in the queue after drain.

    The publish loop records each per-message outcome in a summary
    counter. After the broker has had 30s to drain, basic_get drains
    the queue and we compare the OK count against the queue depth.
    """
    raw = rabbit1.succeed("cat /tmp/mempressure-results.json")
    results = json.loads(raw)
    summary = results["publish_summary"]
    final_count = results["final_count"]
    ok = summary["ok"]

    if final_count < 0:
        raise AssertionError(
            "could not parse queue depth from drain output: "
            + str(results.get("final_count"))
        )

    if final_count < ok:
        raise AssertionError(
            "silent message loss under memory pressure: "
            + str(ok) + " confirmed publishes, only "
            + str(final_count) + " retrieved after drain"
        )
    '';
    check = ''
_check("rabbitmq-memory-no-message-loss", check_no_message_loss)
    '';
  };

  # ---------------------------------------------------------------------------
  # No phantom messages: the queue must not contain more messages than were
  # confirmed-published, even after the broker has been through a memory
  # pressure cycle.
  # ---------------------------------------------------------------------------
  no_phantom_messages = {
    name = "rabbitmq-memory-no-phantom-messages";
    setup = ''
def check_no_phantom_messages():
    """Queue depth must not exceed the number of accepted publishes."""
    raw = rabbit1.succeed("cat /tmp/mempressure-results.json")
    results = json.loads(raw)
    summary = results["publish_summary"]
    final_count = results["final_count"]
    ok = summary["ok"]

    if final_count > ok:
        raise AssertionError(
            "phantom messages under memory pressure: "
            + str(ok) + " confirmed publishes, but "
            + str(final_count) + " messages found after drain"
        )
    '';
    check = ''
_check("rabbitmq-memory-no-phantom-messages", check_no_phantom_messages)
    '';
  };

  # ---------------------------------------------------------------------------
  # The cluster must remain healthy throughout: every node must see every
  # other node via cluster_status. A node that died from OOM during the
  # publish burst would show up here as a missing peer.
  # ---------------------------------------------------------------------------
  cluster_remains_healthy = {
    name = "rabbitmq-memory-cluster-remains-healthy";
    setup = ''
def check_cluster_remains_healthy():
    """Every node must report the full 3-node cluster after the drain."""
    for machine in [rabbit1, rabbit2, rabbit3]:
        machine.wait_until_succeeds(
            "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status' > /tmp/cluster-status && "
            "grep -q 'rabbit@rabbit1' /tmp/cluster-status && "
            "grep -q 'rabbit@rabbit2' /tmp/cluster-status && "
            "grep -q 'rabbit@rabbit3' /tmp/cluster-status",
            timeout=60,
        )
    '';
    check = ''
_check("rabbitmq-memory-cluster-remains-healthy", check_cluster_remains_healthy)
    '';
  };

  # ---------------------------------------------------------------------------
  # Memory alarm engages under heavy pressure. When the publish load and
  # watermark combine to a tight setup, the broker should report an active
  # memory alarm at least once during or after the publish phase. We
  # intentionally skip this check for the lightest load (publish_count < 500)
  # because the broker may legitimately stay below its watermark there.
  # ---------------------------------------------------------------------------
  memory_alarm_engages_under_pressure = {
    name = "rabbitmq-memory-alarm-under-pressure";
    setup = ''
def check_memory_alarm_engages_under_pressure():
    """The memory alarm must fire when the load is tight enough.

    Skipped when publish_count < 500 because the broker may
    legitimately stay below its watermark under light load.
    """
    publish_count = int(
        rabbit1.succeed("cat /etc/topotestix-memory-publish-count").strip()
    )
    if publish_count < 500:
        return

    raw = rabbit1.succeed("cat /tmp/mempressure-results.json")
    results = json.loads(raw)
    after_publish = results["alarm_after_publish"]
    after_drain = results["alarm_after_drain"]

    if after_publish != "failed" and after_drain != "failed":
        raise AssertionError(
            "memory alarm did not engage under heavy pressure "
            "(publish_count=" + str(publish_count) + "): "
            "after_publish=" + after_publish + " "
            "after_drain=" + after_drain
        )
    '';
    check = ''
_check("rabbitmq-memory-alarm-under-pressure", check_memory_alarm_engages_under_pressure)
    '';
  };

  # ---------------------------------------------------------------------------
  # Service liveness: every node's rabbitmq.service must still be active
  # after the memory pressure cycle. A node that OOM-died would fail here.
  # ---------------------------------------------------------------------------
  service_still_up_after_delay = {
    name = "rabbitmq-memory-still-up";
    setup = ''
def check_service_still_up(machine):
    machine.succeed("systemctl is-active rabbitmq.service")
    '';
    check = ''
_check("rabbitmq-memory-still-up-rabbit1", check_service_still_up, rabbit1)
_check("rabbitmq-memory-still-up-rabbit2", check_service_still_up, rabbit2)
_check("rabbitmq-memory-still-up-rabbit3", check_service_still_up, rabbit3)
    '';
  };
}
