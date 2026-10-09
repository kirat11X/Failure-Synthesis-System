package fss.core;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.Objects;

/**
 * One complete stored event, as returned by retrieval (contract v0 section 5).
 *
 * <p>{@code sourceId} and {@code eventType} are u32 and {@code timestampNs} is u64: Java
 * stores them in signed types, so callers must compare and print them as unsigned. The
 * payload is opaque; the core never interprets it.
 */
public record EventRecord(int sourceId, long timestampNs, int eventType, byte[] payload) {

    public EventRecord {
        Objects.requireNonNull(payload, "payload");
        if (payload.length > EnvelopeCodec.MAX_PAYLOAD_LEN) {
            throw new IllegalArgumentException("payload is " + payload.length
                    + " bytes; max is " + EnvelopeCodec.MAX_PAYLOAD_LEN);
        }
        payload = payload.clone();
    }

    /** Returns a copy; records are immutable evidence. */
    @Override
    public byte[] payload() {
        return payload.clone();
    }

    int payloadLength() {
        return payload.length;
    }

    void putPayload(ByteBuffer dst) {
        dst.put(payload);
    }

    @Override
    public boolean equals(Object o) {
        return o instanceof EventRecord r && sourceId == r.sourceId && timestampNs == r.timestampNs
                && eventType == r.eventType && Arrays.equals(payload, r.payload);
    }

    @Override
    public int hashCode() {
        return Objects.hash(sourceId, timestampNs, eventType, Arrays.hashCode(payload));
    }

    @Override
    public String toString() {
        return "EventRecord[source=" + Integer.toUnsignedString(sourceId)
                + ", ts=" + Long.toUnsignedString(timestampNs)
                + ", type=0x" + Integer.toHexString(eventType).toUpperCase()
                + ", payload=" + payload.length + " bytes]";
    }
}
