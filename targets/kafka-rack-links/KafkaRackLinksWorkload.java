import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.List;
import java.util.Properties;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;

public final class KafkaRackLinksWorkload {
    private KafkaRackLinksWorkload() {}

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            usage();
        }
        switch (args[0]) {
            case "produce":
                produce(args);
                return;
            case "stream":
                stream(args);
                return;
            case "consume":
                consume(args);
                return;
            default:
                usage();
        }
    }

    private static void usage() {
        throw new IllegalArgumentException(
            "usage: produce <bootstrap> <topic> <history> <prefix> <count> <timeout-ms> "
                + "| stream <bootstrap> <topic> <history> <prefix> <duration-ms> <interval-ms> "
                + "<timeout-ms> | consume <bootstrap> <topic> <history> <end-offset> <timeout-ms>"
        );
    }

    private static Properties producerProperties(String bootstrap, int timeoutMs, String clientId) {
        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.ACKS_CONFIG, "all");
        props.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, "true");
        props.put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, "5");
        props.put(ProducerConfig.RETRIES_CONFIG, "3");
        props.put(ProducerConfig.LINGER_MS_CONFIG, "0");
        props.put(ProducerConfig.REQUEST_TIMEOUT_MS_CONFIG, Integer.toString(Math.max(1000, timeoutMs / 2)));
        props.put(ProducerConfig.DELIVERY_TIMEOUT_MS_CONFIG, Integer.toString(timeoutMs));
        props.put(ProducerConfig.MAX_BLOCK_MS_CONFIG, Integer.toString(timeoutMs));
        props.put(ProducerConfig.CLIENT_ID_CONFIG, clientId);
        return props;
    }

    private static BufferedWriter historyWriter(Path history) throws IOException {
        Files.createDirectories(history.toAbsolutePath().getParent());
        return Files.newBufferedWriter(
            history,
            StandardCharsets.UTF_8,
            StandardOpenOption.CREATE,
            StandardOpenOption.TRUNCATE_EXISTING
        );
    }

    // Sends records one at a time and waits for each; stops at the first
    // record that is not confirmed and exits with status 2.
    private static void produce(String[] args) throws Exception {
        if (args.length != 7) {
            usage();
        }
        String bootstrap = args[1];
        String topic = args[2];
        Path history = Path.of(args[3]);
        String prefix = args[4];
        int count = Integer.parseInt(args[5]);
        int timeoutMs = Integer.parseInt(args[6]);

        boolean allConfirmed = true;
        try (
            BufferedWriter writer = historyWriter(history);
            KafkaProducer<String, String> producer = new KafkaProducer<>(
                producerProperties(bootstrap, timeoutMs, "topotestix-kafka-rack-links")
            )
        ) {
            for (int index = 0; index < count && allConfirmed; index++) {
                String opId = String.format("%s/%04d", prefix, index);
                long startedNs = System.currentTimeMillis() * 1_000_000L;
                boolean invoked = false;
                String outcome = "ambiguous";
                RecordMetadata metadata = null;
                Throwable failure = null;
                try {
                    Future<RecordMetadata> future = producer.send(new ProducerRecord<>(topic, 0, opId, opId));
                    invoked = true;
                    metadata = future.get(timeoutMs + 2000L, TimeUnit.MILLISECONDS);
                    outcome = "confirmed";
                } catch (Exception exception) {
                    failure = unwrap(exception);
                    if (!invoked) {
                        outcome = "failed_before_send";
                    }
                    allConfirmed = false;
                }
                writer.write(produceEvent(opId, invoked, outcome, startedNs, metadata, failure));
                writer.newLine();
                writer.flush();
            }
            producer.close(Duration.ofSeconds(2));
        }
        if (!allConfirmed) {
            System.exit(2);
        }
    }

    // Sends one record every interval for the given duration without waiting
    // for earlier sends, then waits for every outstanding send to complete.
    // Each record is written to the history when its outcome is known.
    private static void stream(String[] args) throws Exception {
        if (args.length != 8) {
            usage();
        }
        String bootstrap = args[1];
        String topic = args[2];
        Path history = Path.of(args[3]);
        String prefix = args[4];
        long durationMs = Long.parseLong(args[5]);
        long intervalMs = Long.parseLong(args[6]);
        int timeoutMs = Integer.parseInt(args[7]);

        AtomicReference<IOException> writeFailure = new AtomicReference<>();
        try (
            BufferedWriter writer = historyWriter(history);
            KafkaProducer<String, String> producer = new KafkaProducer<>(
                producerProperties(bootstrap, timeoutMs, "topotestix-kafka-rack-links-stream")
            )
        ) {
            long streamStartedNanos = System.nanoTime();
            for (int index = 0; index * intervalMs < durationMs; index++) {
                long waitNanos = streamStartedNanos
                    + TimeUnit.MILLISECONDS.toNanos(index * intervalMs)
                    - System.nanoTime();
                if (waitNanos > 0) {
                    TimeUnit.NANOSECONDS.sleep(waitNanos);
                }
                String opId = String.format("%s/%05d", prefix, index);
                long startedNs = System.currentTimeMillis() * 1_000_000L;
                try {
                    producer.send(
                        new ProducerRecord<>(topic, 0, opId, opId),
                        (metadata, exception) -> record(
                            writer,
                            writeFailure,
                            produceEvent(
                                opId,
                                true,
                                exception == null ? "confirmed" : "ambiguous",
                                startedNs,
                                exception == null ? metadata : null,
                                exception
                            )
                        )
                    );
                } catch (Exception exception) {
                    record(
                        writer,
                        writeFailure,
                        produceEvent(opId, false, "failed_before_send", startedNs, null, unwrap(exception))
                    );
                }
            }
            producer.flush();
            producer.close(Duration.ofMillis(timeoutMs + 5000L));
        }
        if (writeFailure.get() != null) {
            throw writeFailure.get();
        }
    }

    private static void record(BufferedWriter writer, AtomicReference<IOException> failure, String event) {
        synchronized (writer) {
            try {
                writer.write(event);
                writer.newLine();
                writer.flush();
            } catch (IOException exception) {
                failure.compareAndSet(null, exception);
            }
        }
    }

    private static void consume(String[] args) throws Exception {
        if (args.length != 6) {
            usage();
        }
        String bootstrap = args[1];
        String topic = args[2];
        Path history = Path.of(args[3]);
        long endOffset = Long.parseLong(args[4]);
        long timeoutMs = Long.parseLong(args[5]);
        TopicPartition partition = new TopicPartition(topic, 0);

        Properties props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        props.put(ConsumerConfig.CLIENT_ID_CONFIG, "topotestix-kafka-rack-links-reader");
        // Bounds each blocking call, so an unreadable partition ends in status 3
        // before the overall deadline instead of an exception.
        props.put(ConsumerConfig.DEFAULT_API_TIMEOUT_MS_CONFIG, "10000");

        long deadlineNs = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs);
        boolean complete = false;
        try (
            BufferedWriter writer = historyWriter(history);
            KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props)
        ) {
            consumer.assign(List.of(partition));
            consumer.seekToBeginning(List.of(partition));
            while (System.nanoTime() < deadlineNs) {
                try {
                    ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(500));
                    for (ConsumerRecord<String, String> record : records.records(partition)) {
                        if (record.offset() < endOffset) {
                            writer.write(consumeEvent(record));
                            writer.newLine();
                        }
                    }
                    writer.flush();
                    if (consumer.position(partition) >= endOffset) {
                        complete = true;
                        break;
                    }
                } catch (org.apache.kafka.common.errors.TimeoutException exception) {
                    // The partition did not answer in time; retry until the deadline.
                }
            }
        }
        if (!complete) {
            System.exit(3);
        }
    }

    private static Throwable unwrap(Throwable failure) {
        if (failure instanceof ExecutionException && failure.getCause() != null) {
            return failure.getCause();
        }
        return failure;
    }

    private static String produceEvent(
        String opId,
        boolean invoked,
        String outcome,
        long startedNs,
        RecordMetadata metadata,
        Throwable failure
    ) {
        return "{"
            + "\"op_id\":" + quote(opId)
            + ",\"invoked\":" + invoked
            + ",\"outcome\":" + quote(outcome)
            + ",\"started_wall_ns\":" + startedNs
            + ",\"finished_wall_ns\":" + (System.currentTimeMillis() * 1_000_000L)
            + ",\"partition\":" + (metadata == null ? "null" : metadata.partition())
            + ",\"offset\":" + (metadata == null ? "null" : metadata.offset())
            + ",\"exception_type\":" + quote(failure == null ? null : failure.getClass().getName())
            + ",\"exception_message\":" + quote(failure == null ? null : failure.getMessage())
            + "}";
    }

    private static String consumeEvent(ConsumerRecord<String, String> record) {
        return "{"
            + "\"op_id\":" + quote(record.value())
            + ",\"key_id\":" + quote(record.key())
            + ",\"partition\":" + record.partition()
            + ",\"offset\":" + record.offset()
            + "}";
    }

    private static String quote(String value) {
        if (value == null) {
            return "null";
        }
        StringBuilder escaped = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '\\':
                    escaped.append("\\\\");
                    break;
                case '"':
                    escaped.append("\\\"");
                    break;
                case '\n':
                    escaped.append("\\n");
                    break;
                case '\r':
                    escaped.append("\\r");
                    break;
                case '\t':
                    escaped.append("\\t");
                    break;
                default:
                    if (character < 0x20) {
                        escaped.append(String.format("\\u%04x", (int) character));
                    } else {
                        escaped.append(character);
                    }
            }
        }
        return escaped.append('"').toString();
    }
}
