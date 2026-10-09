# Open questions and recommended next step

## Questions for the mentor

1. **Durability scope.** J1 guarantees process-crash durability for every acknowledged event, and
   that is tested (280 SIGKILL runs, 0 lost). OS-crash/power-loss durability is limited to
   events before the last `sync()`, plus a no-holes prefix per source. That is designed in but
   untested. Is that the target? If power loss matters, J2 needs a group-commit policy and a
   VM or `dm-log-writes` test.
2. **Cost of forcing on block rollover.** To keep a no-holes prefix per source after an OS crash,
   `append()` forces the file when a source moves to a new block. On btrfs that cut kill-test
   throughput by about 10x. The alternative is a per-source sequence number in the record
   header, which would *detect* holes instead of preventing them but needs contract v1. Decide
   with J2 measurements.
3. **Zeroing vs. quarantine.** Recovery zeroes everything after the first bad record in a block,
   as specified. After a mid-block bit flip, that also destroys later records that were valid
   (174k discarded across 20k random flips in test (c)). For forensics, should the tail be copied
   to a quarantine file before it is zeroed?
4. **MAVLink as the payload-schema source** (`event_type = msgid`)? It would need an XML-to-schema
   importer. Today `schema_version` is the decoder's own version and is **not verified against
   the producer**, because the v0 envelope carries no producer schema id. MAVLink's CRC_EXTRA,
   or a v1 envelope field, would close that gap.
5. **Clock basis per source** (UTC vs. time since boot) is not in the contract. Evidence carries
   raw `timestamp_ns`, so nothing can render wall-clock time correctly yet. This must be decided
   before the dashboard and before J3 segments (receive time vs. producer time).
6. **Evidence ordering.** Events are grouped by source, each sorted by its own producer clock,
   with no interleaved cross-drone timeline. That deliberately departs from the handoff §20
   example to avoid implying causal order. Is the mentor OK with that?
7. **Truncated retrieval.** The subset returned is unspecified, and J1 returns the earliest
   events in storage order, which can drop a whole source (for example, all of 298). Options for
   J3: per-source fairness in the cut, or a pagination cursor.
8. **JSON and u64.** ns timestamps (~1.8 × 10¹⁸) exceed JavaScript's 2⁵³ limit, so the I1 HTTP+JSON
   transport and the dashboard must carry them as strings.
9. **Limits.** Are a 1 h `MAX_WINDOW_NS` and a 10 000 `MAX_EVENTS_LIMIT` the right defaults?
   Should they be per-deployment configuration?
10. **All-or-nothing MALFORMED.** A payload that is too short for its schema yields `fields = {}`,
    even when its leading fields were in bounds, because they may be misaligned. Is that the
    right call?
11. **Empty blocks after a crash** are never reused in J1. That costs at most one block per crash
    per allocation in progress, and keeps each source's blocks in file order. Revisit with
    compaction later?

## Recommended next step: **J2 (concurrent ingest)**

- **P1 is complete and unblocked.** The decoder is tested against the frozen contract, and every
  decoder path is already exercised by the fixtures and the fuzz tests. P2 (the real-data
  replayer) adds realism but de-risks nothing structural. It is also independent of the Java
  side, so a second team member can run it in parallel.
- **J2 holds the biggest remaining unknowns**:
  - concurrency: N producers, a bounded queue, a single writer thread and backpressure;
  - the durability policy and its price: force never, group commit or every write, measured
    against the rollover-force cost seen on btrfs. This answers questions 1 and 2 with numbers.
- **The crash harness extends directly to J2.** Kill the writer under concurrent producers,
  with "acknowledged" redefined per commit policy.
- **I1 needs network ingest**, so J2 is on the critical path to the end-to-end "why did 474 leave
  formation" demo.
