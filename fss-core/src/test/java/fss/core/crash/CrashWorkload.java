package fss.core.crash;

import fss.core.BlockStore;
import fss.core.EnvelopeCodec;
import fss.core.EventRecord;
import fss.core.RetrieveRequest;
import fss.core.RetrieveResult;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.SplittableRandom;

/**
 * Deterministic workload shared by the kill-test parent and child JVMs: event {@code seq} of
 * a source is a pure function of (chainSeed, source, seq), so the parent can regenerate
 * every expected byte without trusting the child.
 */
final class CrashWorkload {

    static final int[] SOURCES = {101, 202, 303, 404, 505};
    static final long BASE_TS = 1_791_454_020_000_000_000L;
    static final long STEP_NS = 1_000_000L; // per-source sequence spacing
    /** Sequence numbers per verification window: 5 s < MAX_WINDOW_NS, 5 000 < MAX_EVENTS_LIMIT. */
    static final int WINDOW_SEQS = 5_000;

    private CrashWorkload() {
    }

    static EventRecord event(long chainSeed, int source, long seq) {
        SplittableRandom r = new SplittableRandom(
                chainSeed ^ (source * 0x9E3779B97F4A7C15L) ^ (seq * 0xC2B2AE3D27D4EB4FL));
        // About 1 in 200 events is near block-sized, forcing frequent rollovers.
        int len = r.nextInt(200) == 0
                ? 60_000 + r.nextInt(EnvelopeCodec.MAX_PAYLOAD_LEN - 60_000 + 1)
                : r.nextInt(1_200);
        byte[] payload = new byte[len];
        r.nextBytes(payload);
        return new EventRecord(source, BASE_TS + seq * STEP_NS, 1 + r.nextInt(8), payload);
    }

    /**
     * Reads one source's events with bounded windows, exactly as any client must (no
     * unbounded scan exists). Covers sequence numbers [0, upToSeq).
     */
    static List<EventRecord> readSource(BlockStore store, int source, long upToSeq) throws IOException {
        List<EventRecord> out = new ArrayList<>();
        for (long first = 0; first < upToSeq; first += WINDOW_SEQS) {
            long start = BASE_TS + first * STEP_NS;
            RetrieveResult r = store.retrieve(RetrieveRequest.forSource(source, start,
                    start + WINDOW_SEQS * STEP_NS, RetrieveRequest.MAX_EVENTS_LIMIT));
            if (r.truncated()) {
                throw new IllegalStateException("window unexpectedly truncated");
            }
            out.addAll(r.events());
        }
        return out;
    }
}
