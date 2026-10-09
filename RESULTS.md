# Results: M0 + P1 + J1 (2026-10-08)

Environment: Fedora (Linux 7.2.5), 20 cores. Python 3.13.11, PyYAML 6.0.2, pytest 9.0.2.
Temurin JDK 21.0.10, Maven 3.9.16, JUnit 5.14.4. The crash harness ran on tmpfs; a kill-only
pass ran on btrfs (`/home`).

## M0: contract and fixtures

- `fixtures/generate_fixtures.py --check`: 17/17 generated files reproduce byte-for-byte.
- Shared vectors (CRC-32C, envelope/record encoding, event_id, envelope rejects) pass on **both**
  sides: Python 24/24 and Java 33/33 (Java also runs the 10 record-reject vectors).
- Three independent CRC-32C implementations agree: the generator's bit-by-bit oracle (checked
  against RFC 3720 known answers), the table-driven `fss_py.wire.crc32c`, and the JDK's
  `java.util.zip.CRC32C`.

## P1: Python decoder (`python -m pytest`): **171 passed** in 0.6 s

| File | Tests | Covers |
|---|---:|---|
| `test_wire_vectors.py` | 24 | shared M0 vectors, byte-for-byte |
| `test_fixtures.py` | 8 | the generator is deterministic; **6/6 fixtures decode exactly to the expected JSON** |
| `test_schema.py` | 31 | load-time validation: overlaps, size/type mismatch, missing endian, enum range, reserved `UNKNOWN`, duplicate YAML keys, YAML booleans (`yes`/`ON`) |
| `test_decoder.py` | 43 | all 10 numeric primitives in both byte orders, bool, the four statuses, f32 rendering, NaN/Inf, gaps |
| `test_retriever.py` | 32 | bounded window, max window, `max_events` range, exact `truncated` flag, half-open interval, unsigned extremes |
| `test_evidence.py` | 10 | structure, data gaps, clock caveat, independence from retrieval order, clock-skew fixture |
| `test_hard_rules.py` | 19 | one test for each of the 16 handoff §22 rules (rule 3 is parametrized ×4) |
| `test_fuzz.py` | 4 | 20 000 random payloads; every truncation of every golden payload; 5 000 bit flips; 2 000 corrupted envelope streams |

Fuzz properties: `decode()` never raises; it never returns SUCCESS or any field value for a payload
shorter than its schema; every value equals an independent `struct.unpack`; output is always
strict JSON. An extra run with `FSS_FUZZ_ITERATIONS=300000 FSS_FUZZ_SEED=1` also passed.

## J1: Java store (`mvn test`): **73 passed** in about 5 s

| Class | Tests | Covers |
|---|---:|---|
| `ContractVectorsTest` | 33 | shared vectors, including on-disk record validation |
| `BlockStoreTest` | 13 | one source per block, rollover, a maximum payload filling a block exactly, reopen rebuilds identical metadata, empty blocks after a crash, min/max (not first/last) pruning, unsigned timestamps ≥ 2⁶³, single-writer lock |
| `RetrieveContractTest` | 15 | bounded window, whole-u64 range rejected, `max_events`, exact `truncated` flag, half-open interval, filters |
| `RecoveryManagerTest` | 8 | torn tail, corrupt middle record, garbage tail, zero length followed by data, source mismatch, idempotence, padding of a partial block |
| `CrashHarnessTest` | 4 | reduced versions of (a), (b) and (c) |

## J1 crash harness (`./crash-harness.sh`, default settings, tmpfs)

| Test | Cases | Passed | Failed | Result details | Time |
|---|---:|---:|---:|---|---:|
| (a) SIGKILL under load (12 chains x 5 runs) | 60 runs | 60 | 0 | 60/60 exits were SIGKILL (137); 1,951,696 events acknowledged; **0 acknowledged events lost**; 15 unacknowledged in-flight events recovered (at most 1 per run allowed); **0 corrupt or out-of-sequence records**; partial block allocation padded in 6 runs; store up to 323 MB; recovery up to 69.5 ms | 18 s |
| (b) Truncate at every byte offset | 327,681 offsets | 327,681 | 0 | every recovery returned exactly the oracle's per-source prefix; non-zero torn fragment zeroed in 153,175 cases; 153,191 torn records discarded | 8 s |
| (c) Bit flips: every bit of every record and envelope header | 34,816 | 34,816 | 0 | every scan stopped at the first bad record; **0 corrupted records returned** | 2 s (all of c) |
| (c) Bit flips: random single bit anywhere in the file | 20,000 | 20,000 | 0 | same | |
| (c) Bit flips: 2-3 random bits in one block | 5,000 | 5,000 | 0 | same | |
| (c) Bit flips: bursts of 1-4 corrupted bytes | 5,000 | 5,000 | 0 | same | |

Additional campaigns:

| Run | Result |
|---|---|
| (a) 200 runs (40 chains x 5), seed 42, tmpfs | 200/200 passed. 7,441,072 events acknowledged, **0 lost, 0 corrupt**, 42 in-flight events recovered. SIGKILL **tore a record mid-write in 2 runs**, and recovery discarded and zeroed it (53,859 B and 65,536 B). Partial block allocation padded in 15 runs. |
| (a) 20 runs (4 chains x 5) on **btrfs** | 20/20 passed, 0 lost, 0 corrupt. Throughput is roughly 10x lower than on tmpfs, measured per millisecond of run time (about 1.4k vs 33k acknowledged events per run, with a shorter kill window). The rollover `force()` is a real fdatasync here; see OPEN_QUESTIONS.md. |

### What each check proves

- **(a)** A child JVM appends a deterministic per-source sequence and writes an ack line after
  each `append()` returns. The parent SIGKILLs it, confirms exit 137, recovers the store, and
  reads every source back through bounded `retrieve()` windows. It then requires, per source:
  - every acknowledged event is present;
  - the recovered list equals the first *n* generated events byte for byte (a prefix, no corruption);
  - *n* exceeds the acknowledged count by at most the single in-flight event.

  Runs are chained 5 deep on the same file, so recovery followed by more appends is tested,
  and the child's own recovery must agree with the parent's (idempotence across processes).
- **(b) and (c)** compare against an exact oracle. Every record's position was captured while
  the store was written, so the expected result of each damaged copy is known in advance.

### Notes

- **Bug found and fixed in the harness:** `Process.destroyForcibly()` closes the parent's end of
  the child's stdout at once, discarding ack lines still in the pipe. That under-counted acks
  (16-89 "unacknowledged" recoveries in about 1 in 5 JUnit runs). The error was in the safe
  direction, but it weakened the zero-loss check. The fix was to kill via
  `ProcessHandle.destroyForcibly()`, which sends the same SIGKILL without touching the streams.
- SIGKILL rarely tears a record: the kernel acts on SIGKILL between pages, so small records
  are effectively atomic. Torn large writes did occur (21 padded block allocations and 2 torn
  records across 280 runs). Test (b) covers every possible torn-record position exhaustively.
- **OS crash / power loss was not tested.** That needs a VM or block-device fault injection.
  See CONTRACT.md §8 for what is designed in.
