package fss.core;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.SplittableRandom;

/** Small helpers shared by the unit tests. */
final class TestEvents {

    static final long T0 = 1_791_454_020_000_000_000L;

    private TestEvents() {
    }

    /** Deterministic event: the payload depends only on the arguments. */
    static EventRecord ev(int source, long ts, int type, int payloadLen) {
        byte[] p = new byte[payloadLen];
        new SplittableRandom(source * 31L + ts * 17L + type).nextBytes(p);
        return new EventRecord(source, ts, type, p);
    }

    static RetrieveResult all(BlockStore store) throws IOException {
        return store.retrieve(RetrieveRequest.forAllSources(T0 - 1_000_000_000L, T0 + 3_000_000_000_000L,
                RetrieveRequest.MAX_EVENTS_LIMIT));
    }

    static void writeAt(Path file, long position, byte[] bytes) throws IOException {
        try (FileChannel ch = FileChannel.open(file, StandardOpenOption.WRITE)) {
            BlockStore.writeFully(ch, ByteBuffer.wrap(bytes), position);
        }
    }
}
