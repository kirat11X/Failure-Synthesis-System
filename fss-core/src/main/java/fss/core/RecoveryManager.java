package fss.core;

import static fss.core.EnvelopeCodec.BLOCK_SIZE;
import static fss.core.EnvelopeCodec.MIN_RECORD_SIZE;
import static fss.core.EnvelopeCodec.OFF_SOURCE;
import static fss.core.EnvelopeCodec.OFF_TIMESTAMP;
import static fss.core.EnvelopeCodec.RECORD_HEADER_LEN;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Crash recovery (contract v0 section 4), run every time a store is opened.
 *
 * <p>Each block is scanned from offset 0 until {@code record_len == 0}, a record fails
 * validation (length, CRC-32C, envelope), or a record names a different source than the
 * block's first record. Everything before that point is the block's valid prefix. Any
 * non-zero byte after it is zeroed and forced to disk, so a torn or corrupt record can never
 * be read later or merged with future appends. All metadata is rebuilt from the data;
 * nothing persisted is trusted (J1 persists none).
 */
public final class RecoveryManager {

    record Result(List<BlockMeta> blocks, RecoveryReport report) {
    }

    private static final byte[] ZEROS = new byte[BLOCK_SIZE];

    private RecoveryManager() {
    }

    static Result recover(FileChannel channel) throws IOException {
        long started = System.nanoTime();
        long size = channel.size();
        long padded = 0;
        if (size % BLOCK_SIZE != 0) {
            // A crash while zero-filling a new block leaves a short file. Pad it with zeros
            // rather than cutting it, so no byte is discarded without being checked.
            padded = BLOCK_SIZE - size % BLOCK_SIZE;
            BlockStore.writeFully(channel, ByteBuffer.wrap(ZEROS, 0, (int) padded), size);
            size += padded;
        }
        if (size / BLOCK_SIZE > Integer.MAX_VALUE) {
            throw new IOException("store has more blocks than supported: " + size / BLOCK_SIZE);
        }
        int blockCount = (int) (size / BLOCK_SIZE);

        ByteBuffer buf = ByteBuffer.allocate(BLOCK_SIZE).order(ByteOrder.LITTLE_ENDIAN);
        List<BlockMeta> blocks = new ArrayList<>(blockCount);
        List<RecoveryReport.Truncation> truncations = new ArrayList<>();
        long zeroed = 0;
        long records = 0;
        int empty = 0;
        for (int id = 0; id < blockCount; id++) {
            BlockMeta meta = new BlockMeta(id);
            buf.clear();
            BlockStore.readFully(channel, buf, meta.fileOffset);
            String stopReason = scanBlock(buf, meta);
            int used = meta.usedLen();
            if (Arrays.mismatch(buf.array(), used, BLOCK_SIZE, ZEROS, used, BLOCK_SIZE) != -1) {
                BlockStore.writeFully(channel, ByteBuffer.wrap(ZEROS, used, BLOCK_SIZE - used),
                        meta.fileOffset + used);
                zeroed += BLOCK_SIZE - used;
                truncations.add(new RecoveryReport.Truncation(id, used,
                        stopReason == null ? "NONZERO_TAIL" : stopReason));
            }
            blocks.add(meta);
            records += meta.recordCount();
            if (meta.isEmpty()) {
                empty++;
            }
        }
        if (padded > 0 || zeroed > 0) {
            channel.force(false);
        }
        RecoveryReport report = new RecoveryReport(blockCount, empty, records, padded, zeroed,
                List.copyOf(truncations), System.nanoTime() - started);
        return new Result(blocks, report);
    }

    /**
     * Fills {@code meta} with the block's valid prefix. Returns why the scan stopped before a
     * clean end of data, or null if it reached {@code record_len == 0} or the block end.
     */
    static String scanBlock(ByteBuffer block, BlockMeta meta) {
        int off = 0;
        while (BLOCK_SIZE - off >= MIN_RECORD_SIZE) {
            if (block.getInt(off) == 0) {
                return null;
            }
            EnvelopeCodec.Error err = EnvelopeCodec.checkRecord(block, off, BLOCK_SIZE - off);
            if (err != null) {
                return err.name();
            }
            int envelope = off + RECORD_HEADER_LEN;
            int source = block.getInt(envelope + OFF_SOURCE);
            if (meta.isEmpty()) {
                meta.claim(source);
            } else if (source != meta.sourceId()) {
                return "SOURCE_MISMATCH";
            }
            int size = RECORD_HEADER_LEN + block.getInt(off);
            meta.add(size, block.getLong(envelope + OFF_TIMESTAMP));
            off += size;
        }
        return null;
    }
}
