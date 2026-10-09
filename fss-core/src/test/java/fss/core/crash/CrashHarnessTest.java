package fss.core.crash;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.OutputStream;
import java.io.PrintStream;
import java.nio.file.Path;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * Smaller versions of the three crash tests, so {@code mvn test} exercises them. The full
 * runs reported in RESULTS.md come from {@code ./crash-harness.sh}.
 */
class CrashHarnessTest {

    @TempDir
    static Path dir;
    static SweepStore store;

    @BeforeAll
    static void build() throws Exception {
        store = SweepStore.build(dir);
    }

    @Test
    void sweepStoreHasTheIntendedShape() {
        assertEquals(5, store.blockCount());
        assertEquals(65_536, store.usedLen[2], "block 2 is filled exactly by one maximum-size record");
        assertTrue(store.records.stream().anyMatch(r -> r.event().payload().length == 0));
    }

    @Test
    void sigkillUnderLoadLosesNoAcknowledgedEvent() throws Exception {
        KillTest.Summary s = KillTest.run(dir.resolve("kill"), 2, 3, 150, 7L, 1_000,
                new PrintStream(OutputStream.nullOutputStream()));
        assertTrue(s.passed(), String.join("\n", s.failures()));
        assertEquals(6, s.sigkilled());
        assertTrue(s.acked() > 0);
    }

    @Test
    void truncationAtEveryThirteenthOffset() throws Exception {
        TruncationSweep.Summary s = TruncationSweep.run(store, dir, 8, 13);
        assertTrue(s.ok(), String.join("\n", s.failures()));
    }

    @Test
    void bitFlips() throws Exception {
        BitFlipSweep.Summary s = BitFlipSweep.run(store, dir, 8, 2_000, 11L);
        assertTrue(s.ok(), String.join("\n", s.failures()));
    }
}
