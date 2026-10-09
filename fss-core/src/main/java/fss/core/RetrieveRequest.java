package fss.core;

/**
 * A bounded retrieval request (contract v0 section 5). Invalid requests are rejected, never
 * clamped, so an unbounded request cannot be constructed.
 *
 * <p>Time range is half-open {@code [tStartNs, tEndNs)} over producer timestamps, compared as
 * unsigned u64. Build with {@link #forSource} or {@link #forAllSources}.
 */
public final class RetrieveRequest {

    public static final long MAX_WINDOW_NS = 3_600_000_000_000L;
    public static final int MAX_EVENTS_LIMIT = 10_000;

    private final boolean allSources;
    private final int sourceId;
    private final long tStartNs;
    private final long tEndNs;
    private final boolean anyType;
    private final int eventType;
    private final int maxEvents;

    private RetrieveRequest(boolean allSources, int sourceId, long tStartNs, long tEndNs,
                            boolean anyType, int eventType, int maxEvents) {
        if (Long.compareUnsigned(tEndNs, tStartNs) <= 0) {
            throw new IllegalArgumentException("time range must satisfy t_end > t_start (got ["
                    + Long.toUnsignedString(tStartNs) + ", " + Long.toUnsignedString(tEndNs) + "))");
        }
        if (Long.compareUnsigned(tEndNs - tStartNs, MAX_WINDOW_NS) > 0) {
            throw new IllegalArgumentException("time window " + Long.toUnsignedString(tEndNs - tStartNs)
                    + " ns exceeds MAX_WINDOW_NS=" + MAX_WINDOW_NS);
        }
        if (maxEvents < 1 || maxEvents > MAX_EVENTS_LIMIT) {
            throw new IllegalArgumentException("max_events must be in [1, " + MAX_EVENTS_LIMIT
                    + "], got " + maxEvents);
        }
        this.allSources = allSources;
        this.sourceId = sourceId;
        this.tStartNs = tStartNs;
        this.tEndNs = tEndNs;
        this.anyType = anyType;
        this.eventType = eventType;
        this.maxEvents = maxEvents;
    }

    public static RetrieveRequest forSource(int sourceId, long tStartNs, long tEndNs, int maxEvents) {
        return new RetrieveRequest(false, sourceId, tStartNs, tEndNs, true, 0, maxEvents);
    }

    public static RetrieveRequest forAllSources(long tStartNs, long tEndNs, int maxEvents) {
        return new RetrieveRequest(true, 0, tStartNs, tEndNs, true, 0, maxEvents);
    }

    /** Same request restricted to one numeric event type. */
    public RetrieveRequest withEventType(int type) {
        return new RetrieveRequest(allSources, sourceId, tStartNs, tEndNs, false, type, maxEvents);
    }

    public boolean isAllSources() {
        return allSources;
    }

    public int sourceId() {
        if (allSources) {
            throw new IllegalStateException("request is for ALL sources");
        }
        return sourceId;
    }

    public long tStartNs() {
        return tStartNs;
    }

    public long tEndNs() {
        return tEndNs;
    }

    public int maxEvents() {
        return maxEvents;
    }

    boolean matches(int source, long timestampNs, int type) {
        return (allSources || source == sourceId)
                && Long.compareUnsigned(timestampNs, tStartNs) >= 0
                && Long.compareUnsigned(timestampNs, tEndNs) < 0
                && (anyType || type == eventType);
    }

    @Override
    public String toString() {
        return "retrieve(" + (allSources ? "ALL" : Integer.toUnsignedString(sourceId)) + ", ["
                + Long.toUnsignedString(tStartNs) + ", " + Long.toUnsignedString(tEndNs) + "), type="
                + (anyType ? "any" : "0x" + Integer.toHexString(eventType)) + ", max=" + maxEvents + ")";
    }
}
