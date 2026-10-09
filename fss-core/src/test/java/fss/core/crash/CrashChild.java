package fss.core.crash;

import fss.core.BlockStore;
import fss.core.EventRecord;
import fss.core.RecoveryReport;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Map;
import java.util.SplittableRandom;

/**
 * Child JVM for the kill test: opens (and so recovers) the store, then appends forever until
 * SIGKILLed. After each {@code append()} returns it writes {@code "A <sourceIndex> <seq>\n"}
 * to stdout with a single write(2). That line is the acknowledgement: the parent counts an
 * event as acknowledged only once it has read the complete line.
 *
 * <p>Usage: {@code CrashChild <store> <chainSeed> <syncEvery>}
 */
public final class CrashChild {

    public static void main(String[] args) throws Exception {
        Path storePath = Path.of(args[0]);
        long chainSeed = Long.parseLong(args[1]);
        int syncEvery = Integer.parseInt(args[2]);
        OutputStream out = new FileOutputStream(FileDescriptor.out); // unbuffered: one write per line

        try (BlockStore store = BlockStore.open(storePath)) {
            int[] sources = CrashWorkload.SOURCES;
            Map<Integer, Long> counts = store.recordCountsBySource();
            long[] next = new long[sources.length];
            StringBuilder ready = new StringBuilder();
            RecoveryReport rr = store.recoveryReport();
            ready.append("READY ").append(rr.bytesZeroed()).append(' ').append(rr.bytesPadded());
            for (int i = 0; i < sources.length; i++) {
                next[i] = counts.getOrDefault(sources[i], 0L);
                ready.append(' ').append(next[i]);
            }
            out.write((ready + "\n").getBytes(StandardCharsets.US_ASCII));

            SplittableRandom pick = new SplittableRandom();
            for (long n = 1; ; n++) {
                int i = pick.nextInt(sources.length);
                EventRecord e = CrashWorkload.event(chainSeed, sources[i], next[i]);
                store.append(e);
                out.write(("A " + i + " " + next[i] + "\n").getBytes(StandardCharsets.US_ASCII));
                next[i]++;
                if (syncEvery > 0 && n % syncEvery == 0) {
                    store.sync();
                }
            }
        }
    }
}
