package fss.core;

import java.util.List;

/**
 * Retrieval result (contract v0 section 5). {@code truncated} is true iff more than
 * {@code maxEvents} events matched; the subset returned is then unspecified (J1 returns the
 * earliest in storage-scan order), and the caller must narrow the request.
 */
public record RetrieveResult(List<EventRecord> events, boolean truncated) {
    public RetrieveResult {
        events = List.copyOf(events);
    }
}
