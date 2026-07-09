start_all()


def rabbitmqctl(machine, args):
    machine.succeed(f"su -s /bin/sh rabbitmq -c 'rabbitmqctl {args}'")


def wait_for_rabbit(machine):
    machine.wait_for_unit("rabbitmq.service")
    machine.wait_for_open_port(5672)
    machine.wait_for_open_port(15672)
    machine.wait_until_succeeds("su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'")
    machine.wait_until_succeeds("curl -fsS -u guest:guest http://localhost:15672/api/overview >/dev/null")


for machine in [rabbit1, rabbit2, rabbit3]:
    wait_for_rabbit(machine)

# Build a 3-node RabbitMQ cluster. The nodes start as independent brokers with
# the same Erlang cookie, then rabbit2/rabbit3 join rabbit1.
for machine in [rabbit2, rabbit3]:
    rabbitmqctl(machine, "stop_app")
    rabbitmqctl(machine, "reset")
    rabbitmqctl(machine, "join_cluster rabbit@rabbit1")
    rabbitmqctl(machine, "start_app")

# Wait until every node sees the full cluster. Write status to a file before
# grepping so RabbitMQ CLI does not see a closed pipe from `grep -q`.
for machine in [rabbit1, rabbit2, rabbit3]:
    machine.wait_until_succeeds(
        "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status' > /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit1' /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit2' /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit3' /tmp/rabbitmq-cluster-status",
        timeout=60,
    )

# Baseline smoke: declare a 3-replica quorum queue and publish one persistent
# message with AMQP publisher confirms.
rabbit1.succeed(
    r'''
python3 - <<'PY'
import pika

queue = "topotestix_baseline"
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue=queue,
    durable=True,
    arguments={"x-queue-type": "quorum", "x-quorum-initial-group-size": 3},
)
channel.confirm_delivery()
channel.basic_publish(
    exchange="",
    routing_key=queue,
    body=b"baseline-payload",
    properties=pika.BasicProperties(delivery_mode=2),
    mandatory=True,
)
connection.close()
PY
    '''
)
