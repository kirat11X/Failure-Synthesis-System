package fss.core.crash;

import fss.core.BlockStore;
import fss.core.EventRecord;
import fss.core.RecoveryReport;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.SplittableRandom;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Crash test (a): a child JVM appends continuously and is killed with SIGKILL at a random
 * moment. Runs are chained: each child reopens the store the previous child died on, so
 * recovery followed by more appends is exercised too.
 *
 * <p>After every kill the parent recovers the store and checks, for each source:
 * every acknowledged event is present (zero loss); the recovered events are exactly the
 * first n events of that source's deterministic sequence, byte for byte (a prefix, no
 * corruption); and n exceeds the acknowledged count by at most the one in-flight event.
 */
final class KillTest {

    record Summary(int runs, int sigkilled, long acked, long recovered, long lostAcked,
                   long inFlightRecovered, long corrupt, int tornTailRuns, int paddedRuns,
                   long maxRecoveryMicros, long maxStoreBytes, List<String> failures) {
        boolean passed() {
            return failures.isEmpty();
        }
    }

    private KillTest() {
    }

    static Summary run(Path workDir, int chains, int runsPerChain, int maxDelayMs, long seed,
                       int syncEvery, PrintStream log) throws Exception {
        Files.createDirectories(workDir);
        SplittableRandom rng = new SplittableRandom(seed);
        int[] sources = CrashWorkload.SOURCES;
        List<String> failures = new ArrayList<>();
        int runs = 0;
        int sigkilled = 0;
        int torn = 0;
        int padded = 0;
        long acked = 0;
        long recovered = 0;
        long lost = 0;
        long inFlight = 0;
        long corrupt = 0;
        long maxRecoveryMicros = 0;
        long maxBytes = 0;

        for (int chain = 0; chain < chains; chain++) {
            Path store = workDir.resolve("kill-chain-" + chain + ".dat");
            Files.deleteIfExists(store);
            long chainSeed = rng.nextLong();
            long[] durable = new long[sources.length]; // verified recovered count per source

            for (int gen = 0; gen < runsPerChain; gen++) {
                runs++;
                String tag = "chain " + chain + " run " + gen;
                ProcessBuilder pb = new ProcessBuilder(javaBinary(), "-Xmx512m", "-XX:+UseSerialGC",
                        "-cp", childClasspath(), CrashChild.class.getName(), store.toString(),
                        Long.toString(chainSeed), Integer.toString(syncEvery));
                pb.redirectError(ProcessBuilder.Redirect.appendTo(workDir.resolve("child-stderr.log").toFile()));
                Process child = pb.start();
                AckReader reader = new AckReader(child.getInputStream(), sources.length);
                Thread readerThread = new Thread(reader, "ack-reader");
                readerThread.start();
                if (!reader.ready.await(60, TimeUnit.SECONDS)) {
                    child.destroyForcibly().waitFor();
                    failures.add(tag + ": child never became ready");
                    readerThread.join();
                    continue;
                }
                int delayMs = rng.nextInt(5) == 0 ? rng.nextInt(3) : 3 + rng.nextInt(maxDelayMs);
                Thread.sleep(delayMs);
                // SIGKILL via the ProcessHandle: Process.destroyForcibly() would also close our end
                // of the child's stdout at once, discarding acks still in the pipe (which
                // under-counts acknowledgements and weakens the zero-loss check).
                child.toHandle().destroyForcibly();
                int exit = child.waitFor();
                readerThread.join();
                if (exit == 137) {
                    sigkilled++;
                } else {
                    failures.add(tag + ": child exit code " + exit + " (expected 137 = SIGKILL); see child-stderr.log");
                }
                if (!Arrays.equals(reader.readyCounts, durable) || reader.readyZeroed != 0 || reader.readyPadded != 0) {
                    failures.add(tag + ": child's recovery disagreed with the parent's: counts "
                            + Arrays.toString(reader.readyCounts) + " vs " + Arrays.toString(durable)
                            + ", zeroed=" + reader.readyZeroed + ", padded=" + reader.readyPadded);
                }

                long runAcked = 0;
                long runExtra = 0;
                RecoveryReport rr;
                try (BlockStore s = BlockStore.open(store)) {
                    rr = s.recoveryReport();
                    Map<Integer, Long> counts = s.recordCountsBySource();
                    for (int i = 0; i < sources.length; i++) {
                        long ackedCount = Math.max(durable[i], reader.acked[i]);
                        runAcked += Math.max(0, reader.acked[i] - durable[i]);
                        List<EventRecord> got = CrashWorkload.readSource(s, sources[i], ackedCount + 2);
                        long stored = counts.getOrDefault(sources[i], 0L);
                        if (got.size() != stored) {
                            failures.add(tag + ": source " + sources[i] + " has " + stored
                                    + " stored records but " + got.size() + " in the expected sequence range");
                        }
                        for (int j = 0; j < got.size(); j++) {
                            if (!got.get(j).equals(CrashWorkload.event(chainSeed, sources[i], j))) {
                                corrupt++;
                                failures.add(tag + ": source " + sources[i] + " record " + j
                                        + " is not the event that was appended (corrupt or out of sequence)");
                                break;
                            }
                        }
                        if (got.size() < ackedCount) {
                            lost += ackedCount - got.size();
                            failures.add(tag + ": source " + sources[i] + " lost "
                                    + (ackedCount - got.size()) + " acknowledged events");
                        }
                        runExtra += Math.max(0, got.size() - ackedCount);
                        durable[i] = got.size();
                    }
                }
                if (runExtra > 1) {
                    failures.add(tag + ": " + runExtra + " unacknowledged events recovered; at most 1 can be in flight ("
                            + reader.diagnostics() + ")");
                }
                acked += runAcked;
                inFlight += runExtra;
                if (rr.bytesZeroed() > 0) {
                    torn++;
                }
                if (rr.bytesPadded() > 0) {
                    padded++;
                }
                maxRecoveryMicros = Math.max(maxRecoveryMicros, rr.durationNanos() / 1_000);
                long bytes = Files.size(store);
                maxBytes = Math.max(maxBytes, bytes);
                log.printf("  %-18s kill after %3d ms  exit=%d  new acks=%6d  recovered total=%7d  "
                                + "in-flight recovered=%d  tail zeroed=%dB  padded=%dB  recovery=%.1f ms%n",
                        tag, delayMs, exit, runAcked, Arrays.stream(durable).sum(), runExtra,
                        rr.bytesZeroed(), rr.bytesPadded(), rr.durationNanos() / 1e6);
            }
            recovered += Arrays.stream(durable).sum();
            Files.deleteIfExists(store);
        }
        return new Summary(runs, sigkilled, acked, recovered, lost, inFlight, corrupt, torn, padded,
                maxRecoveryMicros, maxBytes, failures);
    }

    private static String javaBinary() {
        return Path.of(System.getProperty("java.home"), "bin", "java").toString();
    }

    private static String childClasspath() {
        return Stream.of(CrashChild.class, BlockStore.class).map(c -> {
            try {
                return Path.of(c.getProtectionDomain().getCodeSource().getLocation().toURI()).toString();
            } catch (URISyntaxException e) {
                throw new IllegalStateException(e);
            }
        }).distinct().collect(Collectors.joining(File.pathSeparator));
    }

    /** Parses the child's stdout. Only complete lines count; a line cut by the kill is ignored. */
    private static final class AckReader implements Runnable {
        final CountDownLatch ready = new CountDownLatch(1);
        final long[] acked; // per source: last acknowledged seq + 1
        long[] readyCounts;
        long readyZeroed;
        long readyPadded;
        long bytes;
        long lines;
        String lastLine = "";
        Throwable error;
        private final InputStream in;

        AckReader(InputStream in, int sources) {
            this.in = in;
            this.acked = new long[sources];
            this.readyCounts = new long[sources];
        }

        @Override
        public void run() {
            StringBuilder line = new StringBuilder();
            byte[] buf = new byte[1 << 16];
            try (in) {
                for (int n; (n = in.read(buf)) > 0; ) {
                    bytes += n;
                    for (int i = 0; i < n; i++) {
                        if (buf[i] == '\n') {
                            handle(line.toString());
                            line.setLength(0);
                        } else {
                            line.append((char) buf[i]);
                        }
                    }
                }
            } catch (IOException ignored) {
                // The pipe closes when the child dies.
            } catch (RuntimeException ex) {
                error = ex;
            }
        }

        String diagnostics() {
            return "reader read " + bytes + " bytes / " + lines + " lines, last line '" + lastLine + "'"
                    + (error == null ? "" : ", reader failed: " + error);
        }

        private void handle(String l) {
            lines++;
            lastLine = l;
            String[] parts = l.split(" ");
            if (parts[0].equals("A")) {
                acked[Integer.parseInt(parts[1])] = Long.parseLong(parts[2]) + 1;
            } else if (parts[0].equals("READY")) {
                readyZeroed = Long.parseLong(parts[1]);
                readyPadded = Long.parseLong(parts[2]);
                for (int i = 0; i < readyCounts.length; i++) {
                    readyCounts[i] = Long.parseLong(parts[3 + i]);
                }
                ready.countDown();
            }
        }
    }
}
