package fss.core;

import static fss.core.EnvelopeCodec.BLOCK_SIZE;
import static fss.core.TestEvents.T0;
import static fss.core.TestEvents.all;
import static fss.core.TestEvents.ev;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class RecoveryManagerTest {

    @TempDir
    Path dir;

    /** Writes the events with one source and returns each record's end offset in the file. */
    private long[] write(Path file, List<EventRecord> events) throws Exception {
        long[] ends = new long[events.size()];
        try (BlockStore store = BlockStore.open(file)) {
            for (int i = 0; i < events.size(); i++) {
                store.append(events.get(i));
                ends[i] = store.blocks().get(0).usedLen();
            }
        }
        return ends;
    }

    private static List<EventRecord> four() {
        return List.of(ev(1, T0, 1, 40), ev(1, T0 + 1, 1, 50), ev(1, T0 + 2, 1, 60), ev(1, T0 + 3, 1, 70));
    }

    @Test
    void emptyFileRecoversToEmptyStore() throws Exception {
        try (BlockStore store = BlockStore.open(dir.resolve("s.dat"))) {
            assertEquals(0, store.recoveryReport().blocksScanned());
            assertTrue(store.recoveryReport().clean());
        }
    }

    @Test
    void tornLastRecordIsDiscardedAndTheTailZeroed() throws Exception {
        Path file = dir.resolve("s.dat");
        long[] ends = write(file, four());
        try (FileChannel ch = FileChannel.open(file, StandardOpenOption.WRITE)) {
            ch.truncate(ends[2] + 5); // the 4th record is cut 5 bytes in: a torn append
        }
        try (BlockStore store = BlockStore.open(file)) {
            RecoveryReport r = store.recoveryReport();
            assertEquals(3, r.recordsRecovered());
            assertEquals(BLOCK_SIZE - ends[2] - 5, r.bytesPadded());
            assertEquals(BLOCK_SIZE - ends[2], r.bytesZeroed());
            assertEquals(List.of(new RecoveryReport.Truncation(0, (int) ends[2], "CRC_MISMATCH")), r.truncations());
            assertEquals(four().subList(0, 3), all(store).events());
        }
        byte[] raw = Files.readAllBytes(file);
        assertEquals(BLOCK_SIZE, raw.length);
        assertArrayEquals(new byte[BLOCK_SIZE - (int) ends[2]], Arrays.copyOfRange(raw, (int) ends[2], BLOCK_SIZE));
    }

    @Test
    void corruptMiddleRecordStopsTheScanThere() throws Exception {
        Path file = dir.resolve("s.dat");
        long[] ends = write(file, four());
        TestEvents.writeAt(file, ends[0] + 30, new byte[] {(byte) 0xAA}); // inside record #2
        try (BlockStore store = BlockStore.open(file)) {
            assertEquals(List.of(four().get(0)), all(store).events());
            assertEquals("CRC_MISMATCH", store.recoveryReport().truncations().get(0).reason());
        }
    }

    @Test
    void garbageAfterTheLastRecordIsZeroedButRecordsKept() throws Exception {
        Path file = dir.resolve("s.dat");
        long[] ends = write(file, four());
        TestEvents.writeAt(file, BLOCK_SIZE - 3, new byte[] {1, 2, 3});
        try (BlockStore store = BlockStore.open(file)) {
            assertEquals(four(), all(store).events());
            assertEquals("NONZERO_TAIL", store.recoveryReport().truncations().get(0).reason());
            assertEquals(BLOCK_SIZE - ends[3], store.recoveryReport().bytesZeroed());
        }
    }

    @Test
    void zeroLengthFollowedByDataIsTreatedAsADirtyTail() throws Exception {
        Path file = dir.resolve("s.dat");
        long[] ends = write(file, four());
        TestEvents.writeAt(file, ends[1], new byte[4]); // record #3's record_len := 0
        try (BlockStore store = BlockStore.open(file)) {
            assertEquals(four().subList(0, 2), all(store).events());
            assertEquals("NONZERO_TAIL", store.recoveryReport().truncations().get(0).reason());
        }
    }

    @Test
    void recordFromAnotherSourceInsideABlockStopsTheScan() throws Exception {
        Path file = dir.resolve("s.dat");
        long[] ends = write(file, four());
        TestEvents.writeAt(file, ends[3], EnvelopeCodec.encodeRecord(ev(2, T0 + 9, 1, 8)));
        try (BlockStore store = BlockStore.open(file)) {
            assertEquals(four(), all(store).events());
            assertEquals("SOURCE_MISMATCH", store.recoveryReport().truncations().get(0).reason());
        }
    }

    @Test
    void recoveryIsIdempotentAndAppendsResumeAtTheValidPrefix() throws Exception {
        Path file = dir.resolve("s.dat");
        long[] ends = write(file, four());
        try (FileChannel ch = FileChannel.open(file, StandardOpenOption.WRITE)) {
            ch.truncate(ends[3] - 1);
        }
        EventRecord next = ev(1, T0 + 10, 1, 12);
        try (BlockStore store = BlockStore.open(file)) {
            assertTrue(!store.recoveryReport().clean());
            store.append(next);
        }
        try (BlockStore store = BlockStore.open(file)) {
            assertTrue(store.recoveryReport().clean(), "second recovery must change nothing");
            assertEquals(List.of(four().get(0), four().get(1), four().get(2), next), all(store).events());
        }
    }

    @Test
    void partialTrailingBlockIsPaddedNotDiscarded() throws Exception {
        Path file = dir.resolve("s.dat");
        write(file, four());
        TestEvents.writeAt(file, BLOCK_SIZE, new byte[100]); // crash while zero-filling block 1
        try (BlockStore store = BlockStore.open(file)) {
            assertEquals(BLOCK_SIZE - 100, store.recoveryReport().bytesPadded());
            assertEquals(2, store.blocks().size());
            assertTrue(store.blocks().get(1).empty());
            assertEquals(four(), all(store).events());
        }
        assertEquals(2L * BLOCK_SIZE, Files.size(file));
    }
}
