package fss.core;

import static fss.core.EnvelopeCodec.BLOCK_SIZE;
import static fss.core.EnvelopeCodec.OFF_SOURCE;
import static fss.core.EnvelopeCodec.OFF_TIMESTAMP;
import static fss.core.EnvelopeCodec.OFF_TYPE;
import static fss.core.EnvelopeCodec.RECORD_HEADER_LEN;

import java.io.EOFException;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * J1 single-writer event store: one data file of fixed 64 KiB blocks, one source per block,
 * accessed with {@link FileChannel} positional I/O. Opening a store always runs
 * {@link RecoveryManager} first.
 *
 * <h2>Durability</h2>
 * <ul>
 *   <li>{@link #append} returns after the record has been written to the file, which means
 *       it is in the OS page cache. It does not force the data to disk.</li>
 *   <li>{@link #sync} calls {@code FileChannel.force(false)} ({@code fdatasync} on Linux).</li>
 *   <li><b>Process crash</b> (SIGKILL, JVM crash, OOM kill): every event whose {@code append}
 *       returned survives. The page cache belongs to the kernel, not the process. At most the
 *       single in-flight record can be torn, and recovery discards it.</li>
 *   <li><b>OS crash or power loss</b>: every event appended before the last completed
 *       {@code sync()} survives. Later events may be lost, but each source's recovered events
 *       are still a prefix of what it appended, with no holes. That holds because a source's
 *       old block is forced to disk before its next block receives data (one extra
 *       {@code force} per 64 KiB per source). It assumes a device that honours flushes and a
 *       filesystem with standard {@code fdatasync} semantics. It is designed for but not
 *       tested in J1.</li>
 *   <li>{@link #close} does not sync. Call {@link #sync} first when OS-crash durability
 *       matters.</li>
 * </ul>
 *
 * <p>Retrieval returns complete, CRC-checked {@link EventRecord}s and never interprets
 * payload bytes. Methods are synchronized; concurrent ingest is milestone J2.
 */
public final class BlockStore implements AutoCloseable {

    private static final ByteBuffer ZERO_BLOCK = ByteBuffer.allocateDirect(BLOCK_SIZE).asReadOnlyBuffer();

    private final Path path;
    private final FileChannel channel;
    private final FileLock lock;
    private final List<BlockMeta> blocks;
    private final Map<Integer, BlockMeta> activeBySource = new HashMap<>();
    private final RecoveryReport recoveryReport;
    private final ByteBuffer readBuf = ByteBuffer.allocate(BLOCK_SIZE).order(ByteOrder.LITTLE_ENDIAN);
    private boolean failed;
    private boolean closed;

    private BlockStore(Path path, FileChannel channel, FileLock lock, RecoveryManager.Result recovered) {
        this.path = path;
        this.channel = channel;
        this.lock = lock;
        this.blocks = new ArrayList<>(recovered.blocks());
        this.recoveryReport = recovered.report();
        // Blocks are only ever allocated at the end of the file, so a source's
        // highest-numbered block is its most recent one.
        for (BlockMeta b : blocks) {
            if (!b.isEmpty()) {
                activeBySource.put(b.sourceId(), b);
            }
        }
    }

    /** Opens (creating if needed) the store at {@code path}, running crash recovery first. */
    public static BlockStore open(Path path) throws IOException {
        Path file = path.toAbsolutePath();
        boolean created = !Files.exists(file);
        FileChannel channel = FileChannel.open(file, StandardOpenOption.CREATE,
                StandardOpenOption.READ, StandardOpenOption.WRITE);
        try {
            FileLock lock = channel.tryLock();
            if (lock == null) {
                throw new IOException("store is locked by another process: " + file);
            }
            if (created) {
                syncDirectory(file.getParent());
            }
            return new BlockStore(file, channel, lock, RecoveryManager.recover(channel));
        } catch (IOException | RuntimeException | Error ex) {
            channel.close();
            throw ex;
        }
    }

    /**
     * Appends one event. If it does not fit in the source's current block, the rest of that
     * block stays zero and the event goes into a newly allocated block. On an I/O error the
     * store refuses further appends; reopen it to recover.
     */
    public synchronized void append(EventRecord event) throws IOException {
        checkOpen();
        if (failed) {
            throw new IllegalStateException("store failed after an I/O error; reopen it to recover");
        }
        byte[] record = EnvelopeCodec.encodeRecord(event);
        try {
            BlockMeta block = activeBySource.get(event.sourceId());
            if (block == null || block.freeBytes() < record.length) {
                if (block != null) {
                    channel.force(false); // see "OS crash" in the class comment
                }
                block = allocateBlock(event.sourceId());
            }
            writeFully(channel, ByteBuffer.wrap(record), block.fileOffset + block.usedLen());
            block.add(record.length, event.timestampNs());
        } catch (IOException | RuntimeException ex) {
            failed = true;
            throw ex;
        }
    }

    /** Forces all appended records to stable storage ({@code fdatasync}). */
    public synchronized void sync() throws IOException {
        checkOpen();
        channel.force(false);
    }

    /**
     * Full scan with block pruning by source and min/max timestamp. Stops after
     * {@code maxEvents} matches and sets {@code truncated} if one more match exists.
     */
    public synchronized RetrieveResult retrieve(RetrieveRequest q) throws IOException {
        checkOpen();
        List<EventRecord> out = new ArrayList<>();
        for (BlockMeta block : blocks) {
            if (!block.mayMatch(q)) {
                continue;
            }
            int used = block.usedLen();
            ByteBuffer buf = readBuf.clear().limit(used);
            readFully(channel, buf, block.fileOffset);
            for (int off = 0; off < used; ) {
                EnvelopeCodec.Error err = EnvelopeCodec.checkRecord(buf, off, used - off);
                if (err != null) {
                    throw new StoreCorruptedException("block " + block.blockId + " offset " + off
                            + " failed validation after recovery: " + err);
                }
                int recordLen = buf.getInt(off);
                int envelope = off + RECORD_HEADER_LEN;
                if (q.matches(buf.getInt(envelope + OFF_SOURCE), buf.getLong(envelope + OFF_TIMESTAMP),
                        buf.getInt(envelope + OFF_TYPE))) {
                    if (out.size() == q.maxEvents()) {
                        return new RetrieveResult(out, true);
                    }
                    out.add(EnvelopeCodec.decodeEnvelope(buf, envelope, recordLen));
                }
                off += RECORD_HEADER_LEN + recordLen;
            }
        }
        return new RetrieveResult(out, false);
    }

    public RecoveryReport recoveryReport() {
        return recoveryReport;
    }

    /** Snapshot of the rebuilt block metadata (diagnostics only; never sent to Python). */
    public synchronized List<BlockInfo> blocks() {
        return blocks.stream().map(BlockMeta::snapshot).toList();
    }

    /** Number of stored records per source, ordered by unsigned source id. */
    public synchronized Map<Integer, Long> recordCountsBySource() {
        Map<Integer, Long> counts = new TreeMap<>(Integer::compareUnsigned);
        for (BlockMeta b : blocks) {
            if (!b.isEmpty()) {
                counts.merge(b.sourceId(), (long) b.recordCount(), Long::sum);
            }
        }
        return counts;
    }

    public Path path() {
        return path;
    }

    @Override
    public synchronized void close() throws IOException {
        if (closed) {
            return;
        }
        closed = true;
        try {
            lock.release();
        } finally {
            channel.close();
        }
    }

    private BlockMeta allocateBlock(int sourceId) throws IOException {
        BlockMeta block = new BlockMeta(blocks.size());
        writeFully(channel, ZERO_BLOCK.duplicate(), block.fileOffset);
        block.claim(sourceId);
        blocks.add(block);
        activeBySource.put(sourceId, block);
        return block;
    }

    private void checkOpen() {
        if (closed) {
            throw new IllegalStateException("store is closed");
        }
    }

    static void writeFully(FileChannel ch, ByteBuffer src, long position) throws IOException {
        while (src.hasRemaining()) {
            position += ch.write(src, position);
        }
    }

    static void readFully(FileChannel ch, ByteBuffer dst, long position) throws IOException {
        while (dst.hasRemaining()) {
            int n = ch.read(dst, position);
            if (n < 0) {
                throw new EOFException("unexpected end of store file at " + position);
            }
            position += n;
        }
    }

    /** Makes a newly created file's directory entry durable (best effort; Linux supports it). */
    private static void syncDirectory(Path dir) {
        try (FileChannel d = FileChannel.open(dir, StandardOpenOption.READ)) {
            d.force(true);
        } catch (IOException | UnsupportedOperationException ignored) {
            // Not supported on every platform; only matters for OS-crash durability of a new file.
        }
    }
}
