package fss.core;

/**
 * Read-only snapshot of one block's rebuilt metadata, for diagnostics and the crash harness.
 * Never exposed through retrieval (storage internals stay hidden from Python).
 * {@code sourceId}, {@code minTsNs} and {@code maxTsNs} are meaningless when {@code empty}.
 */
public record BlockInfo(int blockId, long fileOffset, boolean empty, int sourceId, int usedLen,
                        int recordCount, long minTsNs, long maxTsNs) {
}
