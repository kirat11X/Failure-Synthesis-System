package fss.core.crash;

import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Runs the three J1 crash tests and prints a results table (markdown).
 *
 * <pre>
 * ./crash-harness.sh [--tests abc] [--kill-chains 12] [--kill-runs-per-chain 5] [--kill-max-delay-ms 300]
 *                    [--sync-every 5000] [--flips 20000] [--truncation-stride 1] [--threads N]
 *                    [--dir PATH] [--seed S]
 * </pre>
 *
 * Exits 1 if any check fails.
 */
public final class CrashHarness {

    public static void main(String[] args) throws Exception {
        String tests = "abc";
        int chains = 12;
        int perChain = 5;
        int maxDelay = 300;
        int flips = 20_000;
        int syncEvery = 5_000;
        int stride = 1;
        int threads = Math.min(16, Runtime.getRuntime().availableProcessors());
        long seed = 20261008L;
        Path dir = Path.of(System.getProperty("java.io.tmpdir"), "fss-crash-" + ProcessHandle.current().pid());
        for (int i = 0; i < args.length; i += 2) {
            String v = args[i + 1];
            switch (args[i]) {
                case "--tests" -> tests = v;
                case "--kill-chains" -> chains = Integer.parseInt(v);
                case "--kill-runs-per-chain" -> perChain = Integer.parseInt(v);
                case "--kill-max-delay-ms" -> maxDelay = Integer.parseInt(v);
                case "--sync-every" -> syncEvery = Integer.parseInt(v);
                case "--flips" -> flips = Integer.parseInt(v);
                case "--truncation-stride" -> stride = Integer.parseInt(v);
                case "--threads" -> threads = Integer.parseInt(v);
                case "--dir" -> dir = Path.of(v);
                case "--seed" -> seed = Long.parseLong(v);
                default -> throw new IllegalArgumentException("unknown option " + args[i]);
            }
        }
        Files.createDirectories(dir);
        PrintStream out = System.out;
        out.printf("FSS J1 crash harness: tests=%s dir=%s (%s) seed=%d threads=%d java=%s%n%n", tests, dir,
                Files.getFileStore(dir).type(), seed, threads, System.getProperty("java.version"));

        List<String> rows = new ArrayList<>();
        List<String> failures = new ArrayList<>();
        if (tests.contains("a")) {
            long t0 = System.nanoTime();
            out.println("(a) SIGKILL under continuous appends");
            KillTest.Summary kill = KillTest.run(dir, chains, perChain, maxDelay, seed, syncEvery, out);
            int failed = failedRuns(kill);
            rows.add(String.format(Locale.ROOT, "| (a) SIGKILL under load (%d chains x %d runs) | %d runs | %d | %d | "
                            + "%d/%d exits were SIGKILL (137); %,d events acknowledged; **%d acknowledged events lost**; "
                            + "%d unacknowledged in-flight events recovered (at most 1 per run allowed); "
                            + "**%d corrupt or out-of-sequence records**; torn record zeroed in %d runs; "
                            + "partial block allocation padded in %d runs; store up to %.0f MB; recovery up to %.1f ms | %.0f s |",
                    chains, perChain, kill.runs(), kill.runs() - failed, failed, kill.sigkilled(), kill.runs(),
                    kill.acked(), kill.lostAcked(), kill.inFlightRecovered(), kill.corrupt(), kill.tornTailRuns(),
                    kill.paddedRuns(), kill.maxStoreBytes() / 1e6, kill.maxRecoveryMicros() / 1e3,
                    (System.nanoTime() - t0) / 1e9));
            kill.failures().forEach(f -> failures.add("(a) " + f));
        }
        if (tests.contains("b") || tests.contains("c")) {
            SweepStore store = SweepStore.build(dir);
            out.printf("%n(b)/(c) sweep store: %d bytes, %d blocks, %d records, 3 sources%n",
                    store.pristine.length, store.blockCount(), store.records.size());
            if (tests.contains("b")) {
                long t1 = System.nanoTime();
                TruncationSweep.Summary trunc = TruncationSweep.run(store, dir, threads, stride);
                long failed = trunc.cases() - trunc.passed();
                rows.add(String.format(Locale.ROOT, "| (b) Truncate at %s byte offset | %,d offsets | %,d | %,d | %s; "
                                + "non-zero torn fragment zeroed in %,d cases; %,d torn records discarded | %.0f s |",
                        stride == 1 ? "every" : "every " + stride + "th", trunc.cases(), trunc.passed(), failed,
                        failed == 0 ? "every recovery returned exactly the oracle's per-source prefix"
                                : "**MISMATCHES, see failures**",
                        trunc.dirtyTailCases(), trunc.recordsCut(), (System.nanoTime() - t1) / 1e9));
                trunc.failures().forEach(f -> failures.add("(b) " + f));
            }
            if (tests.contains("c")) {
                long t2 = System.nanoTime();
                BitFlipSweep.Summary flip = BitFlipSweep.run(store, dir, threads, flips, seed);
                double secs = (System.nanoTime() - t2) / 1e9;
                for (BitFlipSweep.KindResult k : flip.kinds()) {
                    long failed = k.trials() - k.passed();
                    rows.add(String.format(Locale.ROOT, "| (c) Bit flips: %s | %,d | %,d | %,d | %s; "
                                    + "%,d records discarded (the bad record and the rest of its block) | %s |",
                            k.kind(), k.trials(), k.passed(), failed,
                            failed == 0 ? "every scan stopped at the first bad record; 0 corrupted records returned"
                                    : "**MISMATCHES, see failures**",
                            k.recordsDiscarded(),
                            k.kind() == BitFlipSweep.Kind.HEADER_EXHAUSTIVE ? String.format(Locale.ROOT, "%.0f s (all kinds)", secs) : ""));
                }
                flip.failures().forEach(f -> failures.add("(c) " + f));
            }
            Files.deleteIfExists(dir.resolve("sweep-pristine.dat"));
        }

        out.println();
        out.println("| Test | Cases | Passed | Failed | Result details | Time |");
        out.println("|---|---:|---:|---:|---|---:|");
        rows.forEach(out::println);
        if (failures.isEmpty()) {
            out.println("\nALL SELECTED CRASH TESTS PASSED");
        } else {
            out.println("\nFAILURES:");
            failures.forEach(f -> out.println("  " + f));
            System.exit(1);
        }
    }

    private static int failedRuns(KillTest.Summary s) {
        return (int) s.failures().stream().map(f -> f.substring(0, f.indexOf(':'))).distinct().count();
    }
}
