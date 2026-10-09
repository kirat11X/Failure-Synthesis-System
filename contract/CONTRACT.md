# FSS Contract v0 (frozen)

This is the single source of truth shared by the Java core (`fss-core/`) and the
Python intelligence layer (`fss_py/`). Changing anything here requires a new
envelope `version` and new vectors. Golden bytes live in `contract/vectors/` and
`fixtures/`, and both are produced by `fixtures/generate_fixtures.py`.

Ownership: Java validates, stores, recovers and retrieves events and never
interprets payload bytes. Python decodes payloads and builds evidence, and never
reads Java storage files.

## 1. Conventions

- All multi-byte integers are **little-endian**.
- `u8/u16/u32/u64` are unsigned. In languages with signed types (Java `int`/`long`), every
  comparison, range check and text rendering of these values **must be unsigned**
  (`Integer.toUnsignedLong`, `Long.compareUnsigned`, ...). A timestamp ≥ 2⁶³ is valid.
- `timestamp_ns` is the **producer's** timestamp in nanoseconds. It is stored and returned
  verbatim and is never replaced with receive time. Its clock basis (UTC epoch, time since
  boot, ...) is per source and outside v0. Fixtures use UTC epoch ns.

## 2. Event envelope (wire format)

| Offset | Size | Field          | Rule |
|-------:|-----:|----------------|------|
| 0      | 2    | `magic`        | `0xF55A` (on the wire as bytes `5A F5`) |
| 2      | 1    | `version`      | `1` |
| 3      | 1    | `flags`        | must be `0` in v0 (reserved) |
| 4      | 4    | `source_id`    | u32 producer/agent id; every value is a valid id |
| 8      | 8    | `timestamp_ns` | u64 producer timestamp |
| 16     | 4    | `event_type`   | u32; selects the Python decoder schema |
| 20     | 4    | `payload_len`  | u32, at most `MAX_PAYLOAD_LEN` = **65 504** |
| 24     | n    | `payload`      | opaque bytes, `n = payload_len` |

`ENVELOPE_HEADER_LEN = 24`. An envelope buffer is valid only if all of the checks below
pass. They run in this order and the first failure is the error code
(`contract/vectors/envelope_reject.tsv`):

1. `TOO_SHORT`: fewer than 24 bytes
2. `BAD_MAGIC`
3. `BAD_VERSION`
4. `BAD_FLAGS`: flags ≠ 0
5. `PAYLOAD_TOO_LARGE`: `payload_len > 65504`
6. `LENGTH_MISMATCH`: buffer length ≠ `24 + payload_len`

An **envelope stream** is a plain concatenation of envelopes with no padding. Golden
fixtures (`fixtures/golden/*.bin`) are envelope streams. They are wire-format data, not
storage files.

## 3. On-disk record (Java-internal)

| Offset | Size         | Field        | Rule |
|-------:|-------------:|--------------|------|
| 0      | 4            | `record_len` | length of the envelope = `24 + payload_len`; `0` = end of block data |
| 4      | 4            | `crc32c`     | CRC-32C over bytes `[0,4)` followed by `[8, 8+record_len)` |
| 8      | `record_len` | envelope     | as in §2 |

- On-disk size = `8 + record_len`, at most 65 536 (one full block).
- The CRC covers the length field and the envelope, but not the CRC field itself.
- **CRC-32C** (Castagnoli): reflected polynomial `0x82F63B78`, init `0xFFFFFFFF`,
  xorout `0xFFFFFFFF`. The check value of `"123456789"` is `0xE3069283`. Java uses
  `java.util.zip.CRC32C`.

Record validation (`contract/vectors/record_reject.tsv`, checks in order, first failure wins):

1. `BAD_LENGTH`: `record_len < 24`
2. `LENGTH_EXCEEDS_BLOCK`: `8 + record_len` > bytes left in the block
3. `CRC_MISMATCH`
4. The envelope checks from §2 (`BAD_MAGIC`, `BAD_VERSION`, `BAD_FLAGS`, `PAYLOAD_TOO_LARGE`,
   `LENGTH_MISMATCH`)

## 4. Blocks

- `BLOCK_SIZE = 65 536`. Block `i` starts at file offset `i × 65 536`. The data file is a
  sequence of blocks.
- A block is **zero-filled when allocated** with an explicit write of zeros.
- **One source per block.** The owner is the `source_id` of the record at offset 0. A block
  whose first `record_len` is 0 is empty and has no owner.
- Records are packed from offset 0 with no gaps. **No record crosses a block boundary.** If
  a record does not fit in the space left, the source gets a new block and that space stays
  zero.
- Bytes after the last record (the tail) are always zero.

**Recovery scan**, run for each block from offset 0. The scan stops at the first of:

- `record_len == 0`
- any record-validation failure (§3)
- a record whose `source_id` differs from the block owner

Everything before that point is the valid prefix (`used_len`). If any byte after `used_len`
is non-zero, the tail is zeroed and forced to disk. All metadata (owner, `used_len`,
`min_ts`, `max_ts`, record count) is rebuilt from the data. v0 persists no metadata.

## 5. Retrieval

```
retrieve(source, t_start_ns, t_end_ns, event_type?, max_events)
    -> (events: list[EventRecord], truncated: bool)
```

| Parameter    | Rule |
|--------------|------|
| `source`     | a u32 `source_id`, or `ALL`. `ALL` is an API-level sentinel, not an in-band id. |
| `t_start_ns`, `t_end_ns` | Required. Half-open interval `[t_start_ns, t_end_ns)` over producer timestamps. `t_end_ns > t_start_ns` and `t_end_ns − t_start_ns ≤ MAX_WINDOW_NS` = **3 600 000 000 000** (1 h). |
| `event_type` | optional u32 numeric id. Name→id mapping is Python's job (schema registry). |
| `max_events` | required, `1 ≤ max_events ≤ MAX_EVENTS_LIMIT` = **10 000** |

- An invalid request is **rejected with an error and never clamped**. A request with no
  bounded window cannot be expressed.
- Results contain only complete, CRC-valid events matching every filter.
- `truncated = true` if and only if more than `max_events` events matched. The returned
  subset is then **unspecified**: J1 returns the earliest in storage-scan order, and it
  can be missing a whole source. Callers must treat the result as incomplete and narrow the
  request (window, source, type). The evidence builder reports this as a data gap.
- **No ordering guarantee**, within or across sources. Producer timestamps are evidence and
  do not define a global or causal order.

`EventRecord = (source_id u32, timestamp_ns u64, event_type u32, payload_bytes)`. It has no
storage fields (block, offset, segment).

Transport (Java → Python) is milestone I1 and not part of v0.

## 6. event_id

`event_id = "ev-" + first 12 lowercase hex digits of SHA-256(envelope bytes)`, where the
envelope is re-encoded canonically from the EventRecord (version 1, flags 0). It is
derived from content, so it is stable across retrievals and reveals nothing about storage.
Byte-identical events share an id; the evidence builder reports such duplicates.

## 7. Decoding (Python)

A schema maps `event_type → (name, version, fields)`. A field is
`(name, offset, type, size, endian, enum?, enum_field?)`. The types are
`u8 u16 u32 u64 i8 i16 i32 i64 f32 f64 bool`. `size` must equal the type's size, `endian`
(`little`/`big`) is required when `size > 1`, and fields must not overlap. `UNKNOWN` is a
reserved enum label.

| `decode_status`      | When | `fields` | `unknown_bytes` |
|----------------------|------|----------|-----------------|
| `SUCCESS`            | every field decoded, every payload byte covered by a field | all fields | 0 |
| `PARTIALLY_DECODED`  | every field decoded, some bytes not covered by any field (opaque) | all fields | uncovered bytes |
| `UNKNOWN_EVENT_TYPE` | no schema for `event_type` | `{}` | `payload_len` |
| `MALFORMED_PAYLOAD`  | a field is out of bounds or a `bool` byte is not 0/1 | `{}` (all-or-nothing) | `payload_len` |

- **Bounds are checked before every read.** No value is ever produced for bytes that are
  not present.
- Enum fields add `enum_field` (default `<name>_name`) holding the documented label, or the
  literal `UNKNOWN` if the value has no mapping. An unmapped value also adds the warning
  `<field>=<value> has no mapping in enum '<enum>'`. Enum-derived keys are listed in
  `interpreted_fields`, separating documented meaning from decoded fact.
- `MALFORMED_PAYLOAD` reasons:
  `field '<name>' needs bytes <a>..<b> but payload has <n> bytes` (inclusive range), or
  `field '<name>' is bool but byte <a> has value <v> (expected 0 or 1)`.
- `f32` values are reported as the shortest decimal that round-trips to the same f32.
  Non-finite floats are kept, add a warning, and serialize to JSON as `"NaN"`,
  `"Infinity"` or `"-Infinity"`.
- `schema_version` is the version of the decoder schema that was applied. **It is not
  verified against the producer**, because v0 has no producer schema id.

DecodedEvent JSON keys: `event_id, source_id, timestamp_ns, event_type, event_name,
schema_version, decode_status, fields, interpreted_fields, unknown_bytes, reason, warnings,
payload_len`.

## 8. Durability (J1 `BlockStore`)

- `append()` returns once the record is written to the file (OS page cache). `sync()` calls
  `FileChannel.force(false)` (`fdatasync`).
- **Process crash** (SIGKILL, JVM crash, OOM kill): every event whose `append()` returned
  is recovered. At most the one in-flight record can be torn, and it is discarded. The page
  cache belongs to the kernel and survives the process.
- **OS crash / power loss**: every event appended before the last completed `sync()` is
  recovered. Events after that may be lost, but for each source the recovered events are a
  prefix of what it appended, with no holes. This holds because the store also forces on
  every block rollover, so a source's earlier block is durable before its next block gets
  data. It assumes a device that honours flushes and a filesystem with standard
  `fdatasync` semantics (ext4, xfs, btrfs). It is designed for but **not tested** in J1
  (testing it needs a VM or block-device fault injection).
- **Never returning corrupt data** relies on CRC-32C plus structural checks. A corrupted
  record goes undetected with probability about 2⁻³² per random corruption. Every
  single-bit error and every burst of 32 bits or fewer is always detected.
- **Media loss or device destruction** is out of scope (needs replication).

## 9. Test vectors (`contract/vectors/`)

| File | Used by | Content |
|------|---------|---------|
| `crc32c.tsv` | Java + Python | input bytes → CRC-32C, including RFC 3720 known answers |
| `envelope.tsv` | Java + Python | fields ↔ envelope bytes ↔ record bytes ↔ event_id |
| `envelope_reject.tsv` | Java + Python | invalid envelopes → error code |
| `record_reject.tsv` | Java only | invalid on-disk records → error code |

Format: `#` comment lines, one header row, then tab-separated rows. Bytes are lowercase hex.

## 10. Changes from the proposal text (defects fixed in v0)

1. `MAX_PAYLOAD_LEN = 65 504`. A u32 `payload_len` could otherwise exceed a block, and the
   "move to a new block" rule could never succeed.
2. `MAX_WINDOW_NS` (1 h) and `MAX_EVENTS_LIMIT` (10 000). `t_end > t_start` alone allows
   `[0, 2⁶⁴−1)`, which is the whole history.
3. `record_len` is defined as the envelope length and must equal `24 + payload_len`.
   Corrupting the length field then fails a structural check every time, not just the CRC
   most of the time.
4. `UNKNOWN` is a reserved enum label, so "unmapped" can never be confused with a
   documented `UNKNOWN` state.
5. Pinned down: half-open intervals, unsigned semantics, `flags = 0`, the CRC parameters,
   `event_id`, a numeric `event_type` filter, and the meaning of `truncated`.
