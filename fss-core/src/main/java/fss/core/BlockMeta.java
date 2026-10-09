package fss.core;

/**
 * In-memory metadata for one 64 KiB block. It is never persisted in J1: recovery rebuilds it
 * from the records themselves. min/max timestamps (not first/last) are used because
 * producer timestamps need not be monotonic.
 */
final class BlockMeta {

    final int blockId;
    final long fileOffset;
    private boolean owned;
    private int sourceId;
    private int usedLen;
    private int recordCount;
    private long minTsNs;
    private long maxTsNs;

    BlockMeta(int blockId) {
        this.blockId = blockId;
        this.fileOffset = (long) blockId * EnvelopeCodec.BLOCK_SIZE;
    }

    boolean isEmpty() {
        return !owned;
    }

    int sourceId() {
        return sourceId;
    }

    int usedLen() {
        return usedLen;
    }

    int freeBytes() {
        return EnvelopeCodec.BLOCK_SIZE - usedLen;
    }

    int recordCount() {
        return recordCount;
    }

    void claim(int source) {
        owned = true;
        sourceId = source;
    }

    void add(int recordSize, long timestampNs) {
        if (recordCount == 0 || Long.compareUnsigned(timestampNs, minTsNs) < 0) {
            minTsNs = timestampNs;
        }
        if (recordCount == 0 || Long.compareUnsigned(timestampNs, maxTsNs) > 0) {
            maxTsNs = timestampNs;
        }
        usedLen += recordSize;
        recordCount++;
    }

    /** Block-level pruning: false only if no record here can match the request. */
    boolean mayMatch(RetrieveRequest q) {
        return owned
                && (q.isAllSources() || sourceId == q.sourceId())
                && Long.compareUnsigned(maxTsNs, q.tStartNs()) >= 0
                && Long.compareUnsigned(minTsNs, q.tEndNs()) < 0;
    }

    BlockInfo snapshot() {
        return new BlockInfo(blockId, fileOffset, !owned, sourceId, usedLen, recordCount, minTsNs, maxTsNs);
    }
}
