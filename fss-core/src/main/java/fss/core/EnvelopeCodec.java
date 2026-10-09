package fss.core;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.zip.CRC32C;

/**
 * Contract v0 envelope and on-disk record encoding (contract/CONTRACT.md sections 2-3, 6).
 *
 * <p>Reads only the 24-byte envelope header. Payload bytes are copied, never interpreted.
 */
public final class EnvelopeCodec {

    public static final int MAGIC = 0xF55A;
    public static final int VERSION = 1;
    public static final int ENVELOPE_HEADER_LEN = 24;
    public static final int RECORD_HEADER_LEN = 8;
    public static final int BLOCK_SIZE = 65_536;
    public static final int MAX_PAYLOAD_LEN = BLOCK_SIZE - RECORD_HEADER_LEN - ENVELOPE_HEADER_LEN;
    /** Smallest possible on-disk record: header plus an envelope with an empty payload. */
    public static final int MIN_RECORD_SIZE = RECORD_HEADER_LEN + ENVELOPE_HEADER_LEN;

    // Envelope field offsets.
    static final int OFF_MAGIC = 0;
    static final int OFF_VERSION = 2;
    static final int OFF_FLAGS = 3;
    static final int OFF_SOURCE = 4;
    static final int OFF_TIMESTAMP = 8;
    static final int OFF_TYPE = 16;
    static final int OFF_PAYLOAD_LEN = 20;

    /** Validation failures; the names are the error codes used by the shared vectors. */
    public enum Error {
        TOO_SHORT, BAD_MAGIC, BAD_VERSION, BAD_FLAGS, PAYLOAD_TOO_LARGE, LENGTH_MISMATCH,
        BAD_LENGTH, LENGTH_EXCEEDS_BLOCK, CRC_MISMATCH
    }

    public static final class FormatException extends IllegalArgumentException {
        private static final long serialVersionUID = 1L;
        private final Error code;

        FormatException(Error code, String message) {
            super(code + ": " + message);
            this.code = code;
        }

        public Error code() {
            return code;
        }
    }

    private EnvelopeCodec() {
    }

    public static byte[] encodeEnvelope(EventRecord e) {
        ByteBuffer buf = ByteBuffer.allocate(ENVELOPE_HEADER_LEN + e.payloadLength())
                .order(ByteOrder.LITTLE_ENDIAN);
        putEnvelope(buf, e);
        return buf.array();
    }

    /** Encodes {@code record_len | crc32c | envelope}. */
    public static byte[] encodeRecord(EventRecord e) {
        int recordLen = ENVELOPE_HEADER_LEN + e.payloadLength();
        ByteBuffer buf = ByteBuffer.allocate(RECORD_HEADER_LEN + recordLen).order(ByteOrder.LITTLE_ENDIAN);
        buf.putInt(recordLen).putInt(0);
        putEnvelope(buf, e);
        buf.putInt(4, recordCrc(buf, 0, recordLen));
        return buf.array();
    }

    private static void putEnvelope(ByteBuffer buf, EventRecord e) {
        buf.putShort((short) MAGIC).put((byte) VERSION).put((byte) 0)
                .putInt(e.sourceId()).putLong(e.timestampNs()).putInt(e.eventType())
                .putInt(e.payloadLength());
        e.putPayload(buf);
    }

    public static EventRecord decodeEnvelope(byte[] envelope) {
        return decodeEnvelope(ByteBuffer.wrap(envelope).order(ByteOrder.LITTLE_ENDIAN), 0, envelope.length);
    }

    /** Decodes exactly one envelope occupying {@code [offset, offset+length)} of a little-endian buffer. */
    public static EventRecord decodeEnvelope(ByteBuffer buf, int offset, int length) {
        Error err = checkEnvelope(buf, offset, length);
        if (err != null) {
            throw new FormatException(err, "invalid envelope of " + length + " bytes");
        }
        byte[] payload = new byte[length - ENVELOPE_HEADER_LEN];
        buf.get(offset + ENVELOPE_HEADER_LEN, payload);
        return new EventRecord(buf.getInt(offset + OFF_SOURCE), buf.getLong(offset + OFF_TIMESTAMP),
                buf.getInt(offset + OFF_TYPE), payload);
    }

    /** Envelope checks in contract order; returns null when valid. */
    static Error checkEnvelope(ByteBuffer buf, int offset, int length) {
        if (length < ENVELOPE_HEADER_LEN) {
            return Error.TOO_SHORT;
        }
        if ((buf.getShort(offset + OFF_MAGIC) & 0xFFFF) != MAGIC) {
            return Error.BAD_MAGIC;
        }
        if ((buf.get(offset + OFF_VERSION) & 0xFF) != VERSION) {
            return Error.BAD_VERSION;
        }
        if (buf.get(offset + OFF_FLAGS) != 0) {
            return Error.BAD_FLAGS;
        }
        long payloadLen = Integer.toUnsignedLong(buf.getInt(offset + OFF_PAYLOAD_LEN));
        if (payloadLen > MAX_PAYLOAD_LEN) {
            return Error.PAYLOAD_TOO_LARGE;
        }
        if (length != ENVELOPE_HEADER_LEN + payloadLen) {
            return Error.LENGTH_MISMATCH;
        }
        return null;
    }

    /**
     * Validates the on-disk record starting at {@code offset} of a little-endian buffer, where
     * {@code remaining} bytes are left before the end of the block. Returns null when valid.
     * The caller treats {@code record_len == 0} as the end-of-block marker before calling this.
     */
    public static Error checkRecord(ByteBuffer buf, int offset, int remaining) {
        if (remaining < RECORD_HEADER_LEN) {
            return Error.LENGTH_EXCEEDS_BLOCK;
        }
        long recordLen = Integer.toUnsignedLong(buf.getInt(offset));
        if (recordLen < ENVELOPE_HEADER_LEN) {
            return Error.BAD_LENGTH;
        }
        if (RECORD_HEADER_LEN + recordLen > remaining) {
            return Error.LENGTH_EXCEEDS_BLOCK;
        }
        if (buf.getInt(offset + 4) != recordCrc(buf, offset, (int) recordLen)) {
            return Error.CRC_MISMATCH;
        }
        return checkEnvelope(buf, offset + RECORD_HEADER_LEN, (int) recordLen);
    }

    /** CRC-32C over the record_len field followed by the envelope (the CRC field is skipped). */
    static int recordCrc(ByteBuffer buf, int offset, int recordLen) {
        CRC32C crc = new CRC32C();
        crc.update(buf.duplicate().limit(offset + 4).position(offset));
        int start = offset + RECORD_HEADER_LEN;
        crc.update(buf.duplicate().limit(start + recordLen).position(start));
        return (int) crc.getValue();
    }

    public static int crc32c(byte[] data) {
        CRC32C crc = new CRC32C();
        crc.update(data);
        return (int) crc.getValue();
    }

    /** {@code "ev-" + first 12 hex digits of SHA-256(envelope)} (contract section 6). */
    public static String eventId(EventRecord e) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(encodeEnvelope(e));
            return "ev-" + HexFormat.of().formatHex(digest, 0, 6);
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is required by every Java runtime", ex);
        }
    }
}
