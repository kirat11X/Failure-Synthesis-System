package fss.core.crash;

import static fss.core.EnvelopeCodec.BLOCK_SIZE;

import fss.core.BlockInfo;
import fss.core.BlockStore;
import fss.core.EnvelopeCodec;
import fss.core.EventRecord;
import fss.core.RecoveryReport;
import fss.core.RetrieveRequest;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.SplittableRandom;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Predicate;

/**
 * A small deterministic store for the exhaustive sweeps, built through the real
 * {@link BlockStore}. It has 3 sources and 5 blocks: a source that rolls over into a second
 * block, a block filled exactly by one maximum-size record, empty payloads, and record
 * lengths whose low byte is zero. The exact position of every record is captured while it is
 * written, which gives an independent oracle for what recovery must return.
 */
final class SweepStore {

    static final int A = 11;
    static final int B = 22;
    static final int C = 33;
    static final long T0 = CrashWorkload.BASE_TS;

    /** One record and where it was written: block id and [start, end) within the block. */
    record Rec(EventRecord event, int block, int start, int end) {
        long absStart() {
            return (long) block * BLOCK_SIZE + start;
        }

        long absEnd() {
            return (long) block * BLOCK_SIZE + end;
        }
    }

    final byte[] pristine;
    final List<Rec> records;
    final int[] usedLen;
    private final int[] nonZeroPrefix; // nonZeroPrefix[i] = number of non-zero bytes in pristine[0, i)

    private SweepStore(byte[] pristine, List<Rec> records, int[] usedLen) {
        this.pristine = pristine;
        this.records = records;
        this.usedLen = usedLen;
        this.nonZeroPrefix = new int[pristine.length + 1];
        for (int i = 0; i < pristine.length; i++) {
            nonZeroPrefix[i + 1] = nonZeroPrefix[i] + (pristine[i] != 0 ? 1 : 0);
        }
    }

    static SweepStore build(Path dir) throws IOException {
        Files.createDirectories(dir);
        Path file = dir.resolve("sweep-pristine.dat");
        Files.deleteIfExists(file);
        List<Rec> recs = new ArrayList<>();
        int[] used;
        try (BlockStore store = BlockStore.open(file)) {
            for (EventRecord e : plan()) {
                List<BlockInfo> before = store.blocks();
                store.append(e);
                List<BlockInfo> after = store.blocks();
                for (BlockInfo b : after) {
                    int was = b.blockId() < before.size() ? before.get(b.blockId()).usedLen() : 0;
                    if (b.usedLen() != was) {
                        recs.add(new Rec(e, b.blockId(), was, b.usedLen()));
                    }
                }
            }
            used = store.blocks().stream().mapToInt(BlockInfo::usedLen).toArray();
        }
        if (recs.size() != plan().size()) {
            throw new IllegalStateException("could not locate every record");
        }
        return new SweepStore(Files.readAllBytes(file), List.copyOf(recs), used);
    }

    private static List<EventRecord> plan() {
        // 232 and 488 give record_len 256 and 512: their first byte on disk is 0x00.
        int[] sizes = {0, 1, 7, 100, 232, 255, 488, 900, 1500, 2047, 3000, 640};
        List<EventRecord> events = new ArrayList<>();
        long ts = T0;
        for (int i = 0; i < 100; i++) {
            events.add(event(A, ts++, 0x10, sizes[i % sizes.length]));
            if (i % 3 == 0) {
                events.add(event(B, ts++, 0x20, (i * 37) % 600));
            }
            if (i == 30) {
                events.add(event(C, ts++, 0x30, EnvelopeCodec.MAX_PAYLOAD_LEN));
            }
        }
        events.add(event(C, ts, 0x30, 3));
        return events;
    }

    private static EventRecord event(int source, long ts, int type, int len) {
        byte[] p = new byte[len];
        new SplittableRandom(ts).nextBytes(p);
        return new EventRecord(source, ts, type, p);
    }

    int blockCount() {
        return usedLen.length;
    }

    boolean allZero(long from, long to) {
        return nonZeroPrefix[(int) to] - nonZeroPrefix[(int) from] == 0;
    }

    /** The record containing absolute position {@code pos}, or null if it is in a zero tail. */
    Rec recordAt(long pos) {
        for (Rec r : records) {
            if (r.absStart() <= pos && pos < r.absEnd()) {
                return r;
            }
        }
        return null;
    }

    /**
     * Opens (and so recovers) a damaged copy and compares the result with the oracle.
     * Returns null on an exact match, otherwise a description of the first difference.
     */
    String verify(Path file, Predicate<Rec> survives, int blocks, long padded, long zeroed) throws IOException {
        try (BlockStore store = BlockStore.open(file)) {
            RecoveryReport rr = store.recoveryReport();
            if (rr.blocksScanned() != blocks || rr.bytesPadded() != padded || rr.bytesZeroed() != zeroed) {
                return "report blocks/padded/zeroed = " + rr.blocksScanned() + "/" + rr.bytesPadded() + "/"
                        + rr.bytesZeroed() + ", expected " + blocks + "/" + padded + "/" + zeroed
                        + " " + rr.truncations();
            }
            List<EventRecord> got = store.retrieve(RetrieveRequest.forAllSources(T0, T0 + 1_000_000,
                    RetrieveRequest.MAX_EVENTS_LIMIT)).events();
            int expectedTotal = 0;
            for (int source : new int[] {A, B, C}) {
                List<EventRecord> expected = records.stream()
                        .filter(r -> r.event().sourceId() == source && survives.test(r)).map(Rec::event).toList();
                List<EventRecord> actual = got.stream().filter(e -> e.sourceId() == source).toList();
                if (!expected.equals(actual)) {
                    return "source " + source + ": expected " + expected.size() + " records, recovered "
                            + actual.size() + (prefixOf(actual, expected) ? " (prefix)" : " (NOT a prefix)");
                }
                expectedTotal += expected.size();
            }
            if (got.size() != expectedTotal) {
                return "recovered " + got.size() + " records, expected " + expectedTotal;
            }
            return null;
        }
    }

    private static boolean prefixOf(List<EventRecord> a, List<EventRecord> b) {
        return a.size() <= b.size() && a.equals(b.subList(0, a.size()));
    }

    static void writeFile(Path file, byte[] data, int length) throws IOException {
        try (FileChannel ch = FileChannel.open(file, StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                StandardOpenOption.TRUNCATE_EXISTING)) {
            ByteBuffer buf = ByteBuffer.wrap(data, 0, length);
            while (buf.hasRemaining()) {
                ch.write(buf);
            }
        }
    }

    interface Trial {
        void run(long index, Path file, byte[] scratch) throws Exception;
    }

    /** Runs trials 0..count-1 on worker threads, each with its own file and a copy of the pristine bytes. */
    void parallel(long count, int threads, Path dir, String prefix, Trial trial) throws Exception {
        AtomicLong next = new AtomicLong();
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        try {
            List<Future<?>> futures = new ArrayList<>();
            for (int t = 0; t < threads; t++) {
                Path file = dir.resolve(prefix + "-" + t + ".dat");
                futures.add(pool.submit(() -> {
                    byte[] scratch = pristine.clone();
                    for (long i; (i = next.getAndIncrement()) < count; ) {
                        trial.run(i, file, scratch);
                    }
                    Files.deleteIfExists(file);
                    return null;
                }));
            }
            for (Future<?> f : futures) {
                f.get();
            }
        } finally {
            pool.shutdownNow();
        }
    }
}
