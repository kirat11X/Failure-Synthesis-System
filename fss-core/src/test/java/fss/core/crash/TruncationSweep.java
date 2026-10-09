package fss.core.crash;

import static fss.core.EnvelopeCodec.BLOCK_SIZE;

import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.LongAdder;

/**
 * Crash test (b): cut the store file at every byte offset 0..length and recover each copy.
 *
 * <p>Oracle: the file is the pristine prefix [0, k), padded back to whole blocks with zeros,
 * as a torn write into a zero-preallocated block leaves it. A record survives if it ends at or
 * before k, or if every byte it lost was zero anyway (the padded copy is then byte-identical).
 * Everything else must be gone, and the block's tail must be zeroed exactly when a non-zero
 * fragment remains.
 */
final class TruncationSweep {

    record Summary(long cases, long passed, long dirtyTailCases, long recordsCut, List<String> failures) {
        boolean ok() {
            return failures.isEmpty() && passed == cases;
        }
    }

    private TruncationSweep() {
    }

    static Summary run(SweepStore s, Path dir, int threads, int stride) throws Exception {
        int length = s.pristine.length;
        long cases = length / stride + 1;
        LongAdder passed = new LongAdder();
        LongAdder dirty = new LongAdder();
        LongAdder cut = new LongAdder();
        ConcurrentLinkedQueue<String> failures = new ConcurrentLinkedQueue<>();

        s.parallel(cases, threads, dir, "trunc", (i, file, scratch) -> {
            int k = (int) Math.min(i * stride, length);
            SweepStore.writeFile(file, s.pristine, k);
            int blocks = (k + BLOCK_SIZE - 1) / BLOCK_SIZE;
            long padded = k % BLOCK_SIZE == 0 ? 0 : BLOCK_SIZE - k % BLOCK_SIZE;
            long zeroed = 0;
            if (k % BLOCK_SIZE != 0) {
                long blockStart = (long) (k / BLOCK_SIZE) * BLOCK_SIZE;
                long validEnd = blockStart;
                for (SweepStore.Rec r : s.records) {
                    if (r.absStart() >= blockStart && r.absStart() < k && survives(s, r, k)) {
                        validEnd = Math.max(validEnd, r.absEnd());
                    }
                }
                if (validEnd < k && !s.allZero(validEnd, k)) {
                    zeroed = blockStart + BLOCK_SIZE - validEnd;
                    dirty.increment();
                }
            }
            for (SweepStore.Rec r : s.records) {
                if (r.absStart() < k && !survives(s, r, k)) {
                    cut.increment();
                }
            }
            String err = s.verify(file, r -> survives(s, r, k), blocks, padded, zeroed);
            if (err == null) {
                passed.increment();
            } else if (failures.size() < 20) {
                failures.add("truncate at " + k + ": " + err);
            }
        });
        return new Summary(cases, passed.sum(), dirty.sum(), cut.sum(), List.copyOf(failures));
    }

    private static boolean survives(SweepStore s, SweepStore.Rec r, long k) {
        return r.absEnd() <= k || (r.absStart() < k && s.allZero(k, r.absEnd()));
    }
}
