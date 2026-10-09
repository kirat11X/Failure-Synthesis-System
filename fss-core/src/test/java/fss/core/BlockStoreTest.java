package fss.core;

import static fss.core.EnvelopeCodec.BLOCK_SIZE;
import static fss.core.EnvelopeCodec.MAX_PAYLOAD_LEN;
import static fss.core.EnvelopeCodec.MIN_RECORD_SIZE;
import static fss.core.TestEvents.T0;
import static fss.core.TestEvents.all;
import static fss.core.TestEvents.ev;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class BlockStoreTest {

    @TempDir
    Path dir;

    @Test
    void appendThenRetrieveReturnsIdenticalRecords() throws Exception {
        List<EventRecord> written = List.of(ev(298, T0 + 1, 0x10, 6), ev(474, T0 + 2, 0x20, 7),
                ev(298, T0 + 3, 0x30, 0));
        try (BlockStore store = BlockStore.open(dir.resolve("s.dat"))) {
            for (EventRecord e : written) {
                store.append(e);
            }
            RetrieveResult r = all(store);
            assertFalse(r.truncated());
            assertEquals(written.size(), r.events().size());
            assertTrue(r.events().containsAll(written));
        }
    }

    @Test
    void eachBlockHoldsOneSource() throws Exception {
        Path file = dir.resolve("s.dat");
        try (BlockStore store = BlockStore.open(file)) {
            for (int i = 0; i < 300; i++) {
                store.append(ev(1 + i % 3, T0 + i, 1, 700));
            }
            assertTrue(store.blocks().size() > 3, "interleaved sources must still get separate blocks");
            assertEquals(Map.of(1, 100L, 2, 100L, 3, 100L), store.recordCountsBySource());
        }
        // Recovery stops at the first record whose source differs from its block's owner,
        // so a clean reopen that recovers all 300 records proves no block mixes sources.
        try (BlockStore store = BlockStore.open(file)) {
            assertTrue(store.recoveryReport().clean());
            assertEquals(300, store.recoveryReport().recordsRecovered());
        }
    }

    @Test
    void recordThatDoesNotFitStartsANewBlockAndLeavesTheTailZero() throws Exception {
        Path file = dir.resolve("s.dat");
        try (BlockStore store = BlockStore.open(file)) {
            int i = 0;
            while (store.blocks().size() < 2) {
                store.append(ev(9, T0 + i, 1, 1000 + i));
                i++;
            }
            BlockInfo first = store.blocks().get(0);
            assertTrue(first.usedLen() < BLOCK_SIZE);
            assertTrue(BLOCK_SIZE - first.usedLen() < MIN_RECORD_SIZE + 1000 + i - 1);
            byte[] raw = Files.readAllBytes(file);
            assertEquals(2L * BLOCK_SIZE, raw.length);
            byte[] tail = Arrays.copyOfRange(raw, first.usedLen(), BLOCK_SIZE);
            assertArrayEquals(new byte[tail.length], tail);
        }
    }

    @Test
    void maximumPayloadFillsABlockExactly() throws Exception {
        try (BlockStore store = BlockStore.open(dir.resolve("s.dat"))) {
            store.append(ev(5, T0, 1, MAX_PAYLOAD_LEN));
            store.append(ev(5, T0 + 1, 1, 0));
            List<BlockInfo> blocks = store.blocks();
            assertEquals(BLOCK_SIZE, blocks.get(0).usedLen());
            assertEquals(MIN_RECORD_SIZE, blocks.get(1).usedLen());
            assertEquals(2, all(store).events().size());
        }
        assertThrows(IllegalArgumentException.class, () -> ev(5, T0, 1, MAX_PAYLOAD_LEN + 1));
    }

    @Test
    void reopenRebuildsTheSameMetadataFromData() throws Exception {
        Path file = dir.resolve("s.dat");
        List<BlockInfo> before;
        List<EventRecord> eventsBefore;
        try (BlockStore store = BlockStore.open(file)) {
            for (int i = 0; i < 500; i++) {
                store.append(ev(10 + i % 4, T0 + (i * 7919L) % 1000, i % 3, (i * 37) % 900));
            }
            before = store.blocks();
            eventsBefore = all(store).events();
        }
        try (BlockStore store = BlockStore.open(file)) {
            assertTrue(store.recoveryReport().clean());
            assertEquals(before, store.blocks());
            assertEquals(eventsBefore, all(store).events());
        }
    }

    @Test
    void appendsContinueInTheRecoveredBlockAfterReopen() throws Exception {
        Path file = dir.resolve("s.dat");
        try (BlockStore store = BlockStore.open(file)) {
            store.append(ev(1, T0, 1, 10));
        }
        try (BlockStore store = BlockStore.open(file)) {
            store.append(ev(1, T0 + 1, 1, 10));
            store.append(ev(2, T0 + 2, 1, 10));
            assertEquals(2, store.blocks().size());
            assertEquals(2, store.blocks().get(0).recordCount());
        }
    }

    @Test
    void emptyBlockLeftByACrashIsNotReusedOrOwned() throws Exception {
        Path file = dir.resolve("s.dat");
        try (BlockStore store = BlockStore.open(file)) {
            store.append(ev(1, T0, 1, 10));
        }
        TestEvents.writeAt(file, BLOCK_SIZE, new byte[BLOCK_SIZE]); // allocated, never written
        try (BlockStore store = BlockStore.open(file)) {
            assertEquals(1, store.recoveryReport().emptyBlocks());
            store.append(ev(2, T0 + 1, 1, 10));
            List<BlockInfo> blocks = store.blocks();
            assertEquals(3, blocks.size());
            assertTrue(blocks.get(1).empty());
            assertEquals(2, blocks.get(2).sourceId());
        }
    }

    @Test
    void outOfOrderTimestampsUseMinMaxNotFirstLast() throws Exception {
        try (BlockStore store = BlockStore.open(dir.resolve("s.dat"))) {
            for (long ts : new long[] {T0 + 500, T0 + 100, T0 + 900, T0 + 300}) {
                store.append(ev(3, ts, 1, 4));
            }
            BlockInfo b = store.blocks().get(0);
            assertEquals(T0 + 100, b.minTsNs());
            assertEquals(T0 + 900, b.maxTsNs());
            assertEquals(1, store.retrieve(RetrieveRequest.forSource(3, T0 + 100, T0 + 101, 10)).events().size());
            assertEquals(1, store.retrieve(RetrieveRequest.forSource(3, T0 + 850, T0 + 950, 10)).events().size());
        }
    }

    @Test
    void timestampsAboveSignedRangeCompareUnsigned() throws Exception {
        long high = Long.MIN_VALUE + 5; // 2^63 + 5 as u64
        try (BlockStore store = BlockStore.open(dir.resolve("s.dat"))) {
            store.append(ev(-1, high, -1, 3)); // source and type 0xFFFFFFFF
            store.append(ev(-1, 10, -1, 3));
            List<EventRecord> top = store.retrieve(RetrieveRequest.forSource(-1, Long.MIN_VALUE,
                    Long.MIN_VALUE + 100, 10)).events();
            assertEquals(List.of(high), top.stream().map(EventRecord::timestampNs).toList());
            List<EventRecord> low = store.retrieve(RetrieveRequest.forSource(-1, 0, 100, 10)).events();
            assertEquals(List.of(10L), low.stream().map(EventRecord::timestampNs).toList());
            BlockInfo b = store.blocks().get(0);
            assertEquals(10L, b.minTsNs());
            assertEquals(high, b.maxTsNs());
        }
    }

    @Test
    void storeFileIsSingleWriter() throws Exception {
        Path file = dir.resolve("s.dat");
        try (BlockStore store = BlockStore.open(file)) {
            assertThrows(Exception.class, () -> BlockStore.open(file).close());
            assertTrue(store.blocks().isEmpty());
        }
        BlockStore.open(file).close(); // lock released on close
    }

    @Test
    void closedStoreRejectsUse() throws Exception {
        BlockStore store = BlockStore.open(dir.resolve("s.dat"));
        store.close();
        assertThrows(IllegalStateException.class, () -> store.append(ev(1, T0, 1, 1)));
        assertThrows(IllegalStateException.class, () -> all(store));
        assertThrows(IllegalStateException.class, store::sync);
    }

    @Test
    void syncIsCallable() throws Exception {
        try (BlockStore store = BlockStore.open(dir.resolve("s.dat"))) {
            store.append(ev(1, T0, 1, 1));
            store.sync();
        }
    }

    @Test
    void manySourcesManyBlocksRoundTrip() throws Exception {
        List<EventRecord> written = new ArrayList<>();
        Path file = dir.resolve("s.dat");
        try (BlockStore store = BlockStore.open(file)) {
            for (int i = 0; i < 3000; i++) {
                EventRecord e = ev(100 + i % 7, T0 + i, i % 5, (i * 131) % 2000);
                store.append(e);
                written.add(e);
            }
        }
        try (BlockStore store = BlockStore.open(file)) {
            for (int s = 100; s < 107; s++) {
                final int src = s;
                List<EventRecord> expected = written.stream().filter(e -> e.sourceId() == src).toList();
                assertEquals(expected, store.retrieve(RetrieveRequest.forSource(src, T0, T0 + 3000, 10_000)).events());
            }
        }
    }
}
