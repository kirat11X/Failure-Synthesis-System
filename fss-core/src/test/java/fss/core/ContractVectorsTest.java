package fss.core;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

/** The shared M0 vectors in contract/vectors: Java must match them byte-for-byte, as Python does. */
class ContractVectorsTest {

    private static final HexFormat HEX = HexFormat.of();

    static List<Map<String, String>> read(String file) throws IOException {
        Path dir = Path.of(System.getProperty("fss.contract.dir", "../contract"), "vectors");
        List<String> lines = Files.readAllLines(dir.resolve(file)).stream()
                .filter(l -> !l.startsWith("#") && !l.isEmpty()).toList();
        String[] header = lines.get(0).split("\t", -1);
        List<Map<String, String>> rows = new ArrayList<>();
        for (String line : lines.subList(1, lines.size())) {
            String[] cells = line.split("\t", -1);
            assertEquals(header.length, cells.length, "malformed row in " + file + ": " + line);
            Map<String, String> row = new LinkedHashMap<>();
            for (int i = 0; i < header.length; i++) {
                row.put(header[i], cells[i]);
            }
            rows.add(row);
        }
        return rows;
    }

    static Stream<Arguments> rows(String file) throws IOException {
        return read(file).stream().map(r -> Arguments.of(r.get("name"), r));
    }

    static Stream<Arguments> crcRows() throws IOException {
        return rows("crc32c.tsv");
    }

    static Stream<Arguments> envelopeRows() throws IOException {
        return rows("envelope.tsv");
    }

    static Stream<Arguments> envelopeRejectRows() throws IOException {
        return rows("envelope_reject.tsv");
    }

    static Stream<Arguments> recordRejectRows() throws IOException {
        return rows("record_reject.tsv");
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("crcRows")
    void crc32c(String name, Map<String, String> row) {
        int crc = EnvelopeCodec.crc32c(HEX.parseHex(row.get("input_hex")));
        assertEquals(row.get("crc32c"), String.format("%08x", crc));
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("envelopeRows")
    void envelopeAndRecordEncoding(String name, Map<String, String> row) {
        EventRecord e = new EventRecord(Integer.parseUnsignedInt(row.get("source_id")),
                Long.parseUnsignedLong(row.get("timestamp_ns")),
                Integer.parseUnsignedInt(row.get("event_type")), HEX.parseHex(row.get("payload_hex")));
        assertEquals(row.get("envelope_hex"), HEX.formatHex(EnvelopeCodec.encodeEnvelope(e)));
        assertEquals(row.get("record_hex"), HEX.formatHex(EnvelopeCodec.encodeRecord(e)));
        assertEquals(row.get("event_id"), EnvelopeCodec.eventId(e));
        EventRecord decoded = EnvelopeCodec.decodeEnvelope(HEX.parseHex(row.get("envelope_hex")));
        assertEquals(e, decoded);
        assertArrayEquals(e.payload(), decoded.payload());
        byte[] record = HEX.parseHex(row.get("record_hex"));
        assertNull(EnvelopeCodec.checkRecord(le(record), 0, record.length));
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("envelopeRejectRows")
    void envelopeRejected(String name, Map<String, String> row) {
        var ex = assertThrows(EnvelopeCodec.FormatException.class,
                () -> EnvelopeCodec.decodeEnvelope(HEX.parseHex(row.get("envelope_hex"))));
        assertEquals(row.get("error"), ex.code().name());
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("recordRejectRows")
    void recordValidation(String name, Map<String, String> row) {
        byte[] record = HEX.parseHex(row.get("record_hex"));
        int remaining = Integer.parseInt(row.get("block_remaining"));
        ByteBuffer block = ByteBuffer.allocate(remaining).order(ByteOrder.LITTLE_ENDIAN);
        block.put(0, record);
        EnvelopeCodec.Error err = EnvelopeCodec.checkRecord(block, 0, remaining);
        assertEquals(row.get("error"), err == null ? "OK" : err.name());
    }

    private static ByteBuffer le(byte[] bytes) {
        return ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
    }
}
