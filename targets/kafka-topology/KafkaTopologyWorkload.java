import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
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

public final class KafkaTopologyWorkload {
    private KafkaTopologyWorkload() {}

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            usage();
        }
        switch (args[0]) {
            case "produce":
                produce(args);
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
                + "| consume <bootstrap> <topic> <history> <end-offset> <timeout-ms>"
        );
    }

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
        props.put(ProducerConfig.CLIENT_ID_CONFIG, "topotestix-kafka-topology");

        boolean allConfirmed = true;
        Files.createDirectories(history.toAbsolutePath().getParent());
        try (
            KafkaProducer<String, String> producer = new KafkaProducer<>(props);
            BufferedWriter writer = Files.newBufferedWriter(
                history,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING
            )
        ) {
            for (int index = 0; index < count; index++) {
                String opId = String.format("%s/%04d", prefix, index);
                long startedNs = System.currentTimeMillis() * 1_000_000L;
                boolean invoked = false;
                String outcome = "ambiguous";
                RecordMetadata metadata = null;
                Throwable failure = null;
                AtomicReference<RecordMetadata> callbackMetadata = new AtomicReference<>();
                AtomicReference<Exception> callbackFailure = new AtomicReference<>();
                try {
                    Future<RecordMetadata> future = producer.send(
                        new ProducerRecord<>(topic, 0, opId, opId),
                        (result, exception) -> {
                            callbackMetadata.set(result);
                            callbackFailure.set(exception);
                        }
                    );
                    invoked = true;
                    metadata = future.get(timeoutMs + 2000L, TimeUnit.MILLISECONDS);
                    if (callbackFailure.get() != null) {
                        throw callbackFailure.get();
                    }
                    if (callbackMetadata.get() != null) {
                        metadata = callbackMetadata.get();
                    }
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
        props.put(ConsumerConfig.CLIENT_ID_CONFIG, "topotestix-kafka-topology-reader");

        Files.createDirectories(history.toAbsolutePath().getParent());
        long deadlineNs = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs);
        boolean complete = false;
        try (
            KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
            BufferedWriter writer = Files.newBufferedWriter(
                history,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING
            )
        ) {
            consumer.assign(java.util.List.of(partition));
            consumer.seekToBeginning(java.util.List.of(partition));
            while (System.nanoTime() < deadlineNs) {
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
