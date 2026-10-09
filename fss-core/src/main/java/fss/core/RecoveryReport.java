package fss.core;

import java.util.List;

/**
 * What recovery found and changed when the store was opened.
 *
 * @param truncations one entry per block whose tail was not all zero and was zeroed
 */
public record RecoveryReport(int blocksScanned, int emptyBlocks, long recordsRecovered,
                             long bytesPadded, long bytesZeroed, List<Truncation> truncations,
                             long durationNanos) {

    /** A block tail that was zeroed: everything from {@code validLen} to the block end. */
    public record Truncation(int blockId, int validLen, String reason) {
    }

    /** True if recovery changed nothing on disk. */
    public boolean clean() {
        return bytesPadded == 0 && bytesZeroed == 0;
    }
}
