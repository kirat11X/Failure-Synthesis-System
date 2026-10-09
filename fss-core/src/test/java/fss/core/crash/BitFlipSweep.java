package fss.core.crash;

import static fss.core.EnvelopeCodec.BLOCK_SIZE;
import static fss.core.EnvelopeCodec.MIN_RECORD_SIZE;

import java.nio.file.Path;
import java.util.List;
import java.util.SplittableRandom;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.LongAdder;

/**
 * Crash test (c): corrupt bits in a copy of the store, recover it, and require that each
 * damaged block keeps exactly the records before its first corrupted record. Nothing
 * corrupted, and nothing after the corruption in that block, may be returned. Other blocks
 * must be unaffected.
 *
 * <p>Trial kinds: every bit of every record and envelope header (exhaustive), random single
 * bits anywhere in the file, 2-3 random bits in one block, and bursts of 1-4 corrupted bytes.
 * CRC-32C detects all of these with certainty (single bits, up to 3 bits per record, and
 * bursts of 32 bits or fewer). Length-field damage is also caught by the structural check
 * {@code record_len == 24 + payload_len}.
 */
final class BitFlipSweep {

    enum Kind { HEADER_EXHAUSTIVE, RANDOM_SINGLE_BIT, MULTI_BIT, BURST }

    record KindResult(Kind kind, long trials, long passed, long recordsDiscarded) {
    }

    record Summary(List<KindResult> kinds, List<String> failures) {
        long trials() {
            return kinds.stream().mapToLong(KindResult::trials).sum();
        }

        long passed() {
            return kinds.stream().mapToLong(KindResult::passed).sum();
        }

        boolean ok() {
            return failures.isEmpty() && passed() == trials();
        }
    }

    private BitFlipSweep() {
    }

    static Summary run(SweepStore s, Path dir, int threads, int randomTrials, long seed) throws Exception {
        long headerTrials = (long) s.records.size() * MIN_RECORD_SIZE * 8;
        long multi = randomTrials / 4;
        long burst = randomTrials / 4;
        long[] bounds = {headerTrials, headerTrials + randomTrials, headerTrials + randomTrials + multi,
                headerTrials + randomTrials + multi + burst};
        LongAdder[] passed = {new LongAdder(), new LongAdder(), new LongAdder(), new LongAdder()};
        LongAdder[] discarded = {new LongAdder(), new LongAdder(), new LongAdder(), new LongAdder()};
        ConcurrentLinkedQueue<String> failures = new ConcurrentLinkedQueue<>();
        int length = s.pristine.length;

        s.parallel(bounds[3], threads, dir, "flip", (i, file, scratch) -> {
            int kind = i < bounds[0] ? 0 : i < bounds[1] ? 1 : i < bounds[2] ? 2 : 3;
            SplittableRandom r = new SplittableRandom(seed ^ (i * 0x9E3779B97F4A7C15L));
            TreeMap<Integer, Integer> xor = new TreeMap<>(); // absolute position -> XOR mask
            switch (kind) {
                case 0 -> {
                    SweepStore.Rec rec = s.records.get((int) (i / (MIN_RECORD_SIZE * 8)));
                    int bit = (int) (i % (MIN_RECORD_SIZE * 8));
                    xor.put((int) rec.absStart() + bit / 8, 1 << (bit % 8));
                }
                case 1 -> xor.put(r.nextInt(length), 1 << r.nextInt(8));
                case 2 -> {
                    int block = r.nextInt(s.blockCount());
                    int flips = 2 + r.nextInt(2);
                    while (flips > 0) {
                        int pos = block * BLOCK_SIZE + r.nextInt(BLOCK_SIZE);
                        int mask = 1 << r.nextInt(8);
                        if ((xor.getOrDefault(pos, 0) & mask) == 0) {
                            xor.merge(pos, mask, (a, b) -> a | b);
                            flips--;
                        }
                    }
                }
                default -> {
                    int start = r.nextInt(length);
                    int end = Math.min(start + 1 + r.nextInt(4), (start / BLOCK_SIZE + 1) * BLOCK_SIZE);
                    for (int p = start; p < end; p++) {
                        xor.put(p, 1 + r.nextInt(255));
                    }
                }
            }

            // Oracle: per damaged block, valid data ends at the first corrupted record's start
            // (or at used_len if the first corruption is in the zero tail).
            long[] validEnd = new long[s.blockCount()];
            for (int b = 0; b < validEnd.length; b++) {
                validEnd[b] = (long) b * BLOCK_SIZE + s.usedLen[b];
            }
            boolean[] damaged = new boolean[s.blockCount()];
            for (int pos : xor.keySet()) { // ascending, so the first hit per block wins
                int b = pos / BLOCK_SIZE;
                if (!damaged[b]) {
                    damaged[b] = true;
                    SweepStore.Rec hit = s.recordAt(pos);
                    if (hit != null) {
                        validEnd[b] = hit.absStart();
                    }
                }
            }
            long zeroed = 0;
            for (int b = 0; b < damaged.length; b++) {
                if (damaged[b]) {
                    zeroed += (long) (b + 1) * BLOCK_SIZE - validEnd[b];
                }
            }
            long lost = s.records.stream().filter(rec -> rec.absEnd() > validEnd[rec.block()]).count();

            xor.forEach((pos, mask) -> scratch[pos] ^= (byte) (int) mask);
            try {
                SweepStore.writeFile(file, scratch, length);
            } finally {
                xor.forEach((pos, mask) -> scratch[pos] ^= (byte) (int) mask);
            }
            String err = s.verify(file, rec -> rec.absEnd() <= validEnd[rec.block()], s.blockCount(), 0, zeroed);
            if (err == null) {
                passed[kind].increment();
                discarded[kind].add(lost);
            } else if (failures.size() < 20) {
                failures.add(Kind.values()[kind] + " trial " + i + " " + xor + ": " + err);
            }
        });

        List<KindResult> kinds = List.of(
                new KindResult(Kind.HEADER_EXHAUSTIVE, bounds[0], passed[0].sum(), discarded[0].sum()),
                new KindResult(Kind.RANDOM_SINGLE_BIT, bounds[1] - bounds[0], passed[1].sum(), discarded[1].sum()),
                new KindResult(Kind.MULTI_BIT, bounds[2] - bounds[1], passed[2].sum(), discarded[2].sum()),
                new KindResult(Kind.BURST, bounds[3] - bounds[2], passed[3].sum(), discarded[3].sum()));
        return new Summary(kinds, List.copyOf(failures));
    }
}
