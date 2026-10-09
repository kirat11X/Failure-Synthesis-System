# Failure Synthesis System (FSS)

**Crash-tolerant event logging and evidence-based failure reconstruction for distributed systems**

| Component | Status (verified 2026-10-09, §10) |
|---|---|
| Python intelligence layer (decoding → evidence → knowledge → synthesis → validation) | **Implemented and tested (run 2, commit `70285bd`): 509 test cases, 501 pass, 8 live skipped; all 123 non-live `TEST_CASES.md` IDs pass; SPEC-01..24 and RAG-01..14 pass.** As received it stopped at the evidence builder: knowledge/RAG, the synthesis contract, the LLM client, the validator, progressive retrieval, presentation and schema-pack directories were added by the verification runs and await team review. Live-LLM evaluation (LLM-EVAL) not yet run. |
| Java event core (ingest → persist → recover → retrieve) | Being written by a teammate; outside the Python verification. Run 1 recorded J1 (block store, crash recovery, bounded retrieval, crash harness) with 73 passing tests; run 2 did not run or touch Java. |
| Java ↔ Python integration (I1), dashboard | Not started. `MockRetriever` stands in for the Java client; `streamlit_app.py` is a drone-specific prototype. |

> This document describes **what the system does and how**, the **test catalogue** used to verify it, and the **verification record**. Sections marked *(filled by verification run)* are completed from the actual code and test results. Everything else is the agreed design.

---

## 1. What FSS is

FSS is a general-purpose evidence layer for **any system made of independent event producers**: microservices, industrial machines, vehicle ECUs, warehouse robots, IoT sensors or drones. It does three things:

1. **Preserves evidence.** Events from many sources are stored durably and remain recoverable after the central logger crashes.
2. **Reconstructs context.** For an investigation, it retrieves a *bounded* time window across *one or many* sources. The visible failure and its cause often live in different sources.
3. **Explains, with limits.** Payloads are decoded deterministically from configured schemas, interpreted using documented domain knowledge, and passed to an LLM that synthesises an explanation. Anything the system cannot interpret is reported as unknown, never guessed.

The drone-fleet scenario (Drone 298's LiDAR fault causing Drone 474 to leave formation) is the **running example**, not a constraint. The same code runs every domain in §2.

---

## 2. Generalisation: what is code and what is configuration

| Layer | Fixed in code (domain-agnostic) | Supplied per deployment (configuration) |
|---|---|---|
| Event model | `source_id`, `timestamp`, `event_type`, `payload_bytes` | Meaning of a source (a service, a machine, an ECU, a drone) |
| Envelope | Required metadata fields | Byte layout and offsets of the envelope (NFR-08) |
| Decoding | Primitive types, bounds checks, endianness handling, decode statuses | **Schema pack**: one YAML schema per event type |
| Semantics | Enum resolution mechanism, confidence levels | Enum maps (e.g. `17 → LIDAR_TIMEOUT`, `3 → POOL_EXHAUSTED`) |
| Knowledge | RAG retrieval and context assembly | **Domain documents**: manuals, error-code tables, runbooks |
| Synthesis | Output contract, validator, uncertainty rules | Nothing domain-specific |

**Adding a new domain means adding a schema pack plus domain documents, with zero code changes.** Test G01 enforces this. Test G02 checks that no domain vocabulary appears in core code.

### Example domains (used in the test catalogue)

| Domain | Sources | Example event types | Cross-source failure |
|---|---|---|---|
| D1 Drone fleet | drones | POSITION, LIDAR_STATUS, AVOIDANCE, FORMATION_STATE | LiDAR fault on 298 → avoidance on 474 → 474 leaves formation |
| D2 Microservices | services, DB proxy | REQUEST_METRIC, DB_POOL_STATUS, HTTP_ERROR | DB pool exhausted → order-service latency → payment-service 504s |
| D3 Industrial line | machines, PLCs | TEMP_STATUS, INTERLOCK, CONVEYOR_STATE | Spindle temp sensor drift on A → overheat interlock → conveyor B starved |
| D4 Vehicle (CAN-style, big-endian) | ECUs | WHEEL_SPEED, ECU_FAULT, ABS_STATE, DASH_WARNING | Wheel-speed sensor fault → ABS disabled → dashboard warning |
| D5 Warehouse robots | AGVs | BATTERY, NAV_STATE, REPLAN, TASK_STATE | AGV-12 battery critical, stops in aisle → AGV-7 replans → order delayed |

---

## 3. Architecture

```
 Producers (any domain)
        │  binary events
        ▼
┌──────────────────────── Java core ────────────────────────┐
│ Ingest → Envelope validation → Block store (CRC framed)   │
│        → Crash recovery → Bounded retrieval               │
└───────────────────────────┬───────────────────────────────┘
                            │  EventRecord[] (+ truncated flag)
                            ▼
┌────────────────────── Python layer ───────────────────────┐
│ Retriever client → Schema lookup → Deterministic decoder  │
│ → Enum resolution → Evidence builder → Domain knowledge   │
│ (RAG) → LLM synthesis → Output validator → Presentation   │
└───────────────────────────────────────────────────────────┘
```

**Boundary:** Java decides *what evidence exists* and retrieves it correctly. Python decides *how it is interpreted and explained*.

- Python never reads Java storage files.
- Java never interprets payload bytes.

---

## 4. Contract v0

**Wire envelope** (little-endian):

```
magic u16 | version u8 | flags u8 | source_id u32 | timestamp_ns u64 | event_type u32 | payload_len u32 | payload[payload_len]
```

**On-disk record:**

```
record_len u32 | crc32c u32 | envelope
```

The CRC covers `record_len` plus the envelope.

**Block:** 64 KiB, zero-preallocated, one source per block. No record crosses a block boundary.

**Retrieval:**

```
retrieve(source_id | ALL, t_start_ns, t_end_ns, event_type?, max_events) -> EventRecord[] + truncated
```

- A bounded interval is mandatory, and `t_end > t_start`. The window is at most 1 h (`MAX_WINDOW_NS`) and `1 ≤ max_events ≤ 10 000`. An invalid request is rejected, never clamped.
- Interval semantics are **half-open `[t_start, t_end)`**. *Verified:* both `MockRetriever` and Java J1 implement exactly this (catalogue R03).
- There is no ordering guarantee across sources.

**Timestamps** are the producer's own, preserved as evidence and never replaced by receive time. The Python handoff examples use milliseconds; the contract fixes **u64 nanoseconds**. *Verified:* the code uses u64 ns (`timestamp_ns`) everywhere. The clock basis (UTC or time since boot) is per source and outside v0; fixtures use UTC epoch ns.

---

## 5. Python layer: what each stage does and how

Package `fss_py/`. The pipeline is `investigate()` in `investigate.py`:

```
retrieve (bounded) → decode_all → build_evidence → KnowledgeBase.lookup → build_context
  → LLM (stub or Claude) → parse_output → validate        (+ one optional bounded follow-up retrieve)
```

### 5.1 Retriever interface (`retriever.py`, `model.py`)

- One interface (`Retriever`), with `MockRetriever` (envelope-stream fixtures, used for all tests) as the only implementation so far. The Java client is milestone I1.
- `RetrievalRequest` enforces the contract on the Python side as well:
  - `t_start_ns` and `t_end_ns` are required u64, with `t_end_ns > t_start_ns`;
  - the window is ≤ 1 h;
  - `1 ≤ max_events ≤ 10 000`;
  - `source` is a u32 or the `ALL` sentinel;
  - `event_type` is numeric (names are mapped by `SchemaRegistry.type_id`);
  - `truncated` is true iff more than `max_events` matched.
- Downstream stages accept only `EventRecord` objects. They have no path to storage (catalogue R10 checks this statically).

### 5.2 Schema packs (`schema.py`, `packs.py`)

A **pack** is a directory, one per domain. Five example packs live in `schema_packs/` (D1-D5):

```
schema_packs/<pack>/*.yaml      one event type per file by convention (several per file allowed)
schema_packs/<pack>/docs/*.md   domain documents (§5.5)
```

`discover_packs(root)` loads every subdirectory not starting with `.` or `_`, so a new domain needs no registration code. Each schema file uses this format (D2 example, `schema_packs/d2_microservices/db_pool_status.yaml`):

```yaml
schema_set: d2_microservices
enums:
  pool_state: {0: HEALTHY, 1: SATURATED, 3: POOL_EXHAUSTED}
event_types:
  0x0201:
    name: DB_POOL_STATUS
    version: 1
    fields:
      - {name: pool_id,      offset: 0, type: u16, size: 2, endian: little}
      - {name: active_conns, offset: 2, type: u16, size: 2, endian: little}
      - {name: max_conns,    offset: 4, type: u16, size: 2, endian: little}
      - {name: state_code,   offset: 6, type: u8,  size: 1, enum: pool_state, enum_field: state}
```

**Validated at load, before any decoding:**
- overlapping fields (the error names both);
- size inconsistent with type;
- unknown type names;
- negative offsets, or offsets beyond `MAX_PAYLOAD_LEN`;
- duplicate field or output names;
- duplicate event types or names, within a file and across a pack's files (the error names both files);
- invalid or missing endianness (`endian` is required for multi-byte types);
- enums attached to non-integer fields, and enum codes that don't fit the field type;
- the reserved label `UNKNOWN`;
- unknown keys;
- duplicate YAML keys;
- YAML booleans used as integers or labels.

Packs are loaded with a `SafeLoader` subclass, so `!!python/...` tags are rejected. An empty pack directory loads, with every event `UNKNOWN_EVENT_TYPE`; a schema *file* with no event types is rejected.

**Supported primitives:** `u8 u16 u32 u64 i8 i16 i32 i64 f32 f64 bool`. Each has an explicit size and signedness; endianness comes from the schema. Nothing is inferred.

### 5.3 Deterministic decoder (`decoder.py`)

For each `EventRecord`:

1. **Schema lookup** by `event_type`. If none is found, the status is `UNKNOWN_EVENT_TYPE` with `fields = {}` and `unknown_bytes = payload_len`. The raw payload stays in the `EventRecord`; the `DecodedEvent` carries only `payload_len` and a content-derived `event_id` for traceability.
2. **Bounds check before every read.** If `offset + size > payload_len`, the status is `MALFORMED_PAYLOAD` with reason `field '<name>' needs bytes <a>..<b> but payload has <n> bytes`. Decoding is **all-or-nothing**: fields decoded before the failing one are discarded (`fields = {}`).
3. **Unpack** with an explicit struct format: endianness and type code come from the schema. `f32` values are reported as the shortest decimal that round-trips (`72.4`, not `72.4000015…`).
4. **Enum resolution.** A mapped value gets `<enum_field> = <LABEL>` (default `<field>_name`). An unmapped value gets `UNKNOWN`, keeps its raw value and adds a warning. Enum-derived keys are listed in `interpreted_fields`.
5. **Coverage accounting.** Bytes not covered by any field (gaps or a trailing region) are counted. If any exist and decoding otherwise succeeded, the status is `PARTIALLY_DECODED` with `unknown_bytes = n`.

The output is a `DecodedEvent`:

```json
{
  "event_id": "ev-8afe0ed8c061",
  "source_id": 3,
  "timestamp_ns": 1791468006000000000,
  "event_type": 513,
  "event_name": "DB_POOL_STATUS",
  "schema_version": 1,
  "decode_status": "SUCCESS",
  "fields": {"pool_id": 1, "active_conns": 50, "max_conns": 50,
             "state_code": 3, "state": "POOL_EXHAUSTED"},
  "interpreted_fields": ["state"],
  "unknown_bytes": 0,
  "reason": null,
  "warnings": [],
  "payload_len": 7
}
```

**Status semantics:**

| Status | Meaning | Precedence |
|---|---|---|
| `SUCCESS` | Every schema field decoded; every byte accounted for | lowest |
| `PARTIALLY_DECODED` | Every schema field decoded; some bytes are opaque | |
| `UNKNOWN_EVENT_TYPE` | No schema for this type | |
| `MALFORMED_PAYLOAD` | A schema field lies outside the payload, or a bool byte is not 0/1 | highest |

**Policy points (confirmed by the verification run):**
- Fields decoded before a malformed field are **not kept** (all-or-nothing).
- NaN and ±infinity are kept, add the warning `field '<f>' decoded to a non-finite value (…)`, and serialise to valid JSON as the strings `"NaN"`, `"Infinity"` and `"-Infinity"`. `-0.0` is kept.
- A boolean byte other than 0 or 1 makes the **whole event `MALFORMED_PAYLOAD`**, with reason `field '<f>' is bool but byte <a> has value <v> (expected 0 or 1)`. It is neither coerced nor kept with a warning.

### 5.4 Confidence levels

| Level | Source | Example | How it is treated |
|---|---|---|---|
| Decoded | Deterministic decoding | `active_conns = 50` | Factual event evidence |
| Documented | Enum maps and domain documents | `3 = POOL_EXHAUSTED` | Documented meaning (listed in `interpreted_fields` / `"documented"`) |
| Unknown | Opaque bytes, unknown types, unmapped enums | `8 unknown bytes` | Reported as a data gap; never interpreted |

### 5.5 Domain knowledge and RAG (`knowledge.py`)

- **Deterministic first.** Enum maps resolve codes in the decoder. Documents say what decoded values *mean*; they never take part in decoding (deleting the corpus leaves decoding byte-identical, RAG-01).
- A document is `docs/<name>.md` in a schema pack, with YAML front matter:

  ```
  ---
  title: LiDAR error codes
  kind: error-code-table        # error-code-table | protocol | manual | state-description | architecture | failure-mode
  keys: [LIDAR_TIMEOUT, SENSOR_DISCONNECTED]   # event names / labels the document explains
  codes:                        # optional: code meanings the document defines (MP §8)
    LIDAR_STATUS.status_code: {17: LIDAR_TIMEOUT, 18: SENSOR_DISCONNECTED}
  ---
  <prose; blank lines separate chunks>
  ```

- **Chunks.** Each paragraph is a chunk with document id, chunk id `doc#n`, kind and domain (the pack directory name). Every snippet in the LLM context carries this provenance and the tag `documented` (RAG-09).
- **Query = evidence + question.** Candidates come only from terms present in the decoded evidence (event names, documented labels) or code values a document defines. The question only re-ranks: per document, 10 per matching label, 5 per event name, 5 per code; +1 per question word found in the chunk, its title or keys. Ties break by document id, then chunk number. No embeddings, no vector store: the same evidence always gives the same chunks in the same order (RAG-05, RAG-06).
- **Budget.** At most `top_k` = 8 chunks (`KnowledgeBase(top_k=…)`); a cut is reported as `[KNOWLEDGE_TRUNCATED]`. There is no token budget (VERIFICATION_REPORT D10).
- **Absence and disagreement are reported, never resolved:**
  - a term or code value with no documentation → `[UNDOCUMENTED_VALUE]`, and the LLM is told not to explain it (RAG-07);
  - two documents, or a document and the enum map, disagree → `[KNOWLEDGE_CONFLICT]` with every claim and its source (RAG-02, RAG-08);
  - nothing relevant → `[NO_DOMAIN_DOCUMENTATION]`; the investigation continues (RAG-12).
- **Isolation is by relevance**, not by a domain filter: chunks must match evidence terms, so a microservice investigation retrieves no drone documents even with every pack loaded (RAG-10; D11).
- **Quality** on the 25-query gold set `tests/rag_gold.yaml` (all domains loaded): precision@3 0.913, recall@3 0.955; precision@5 0.890, recall@5 1.000 (run 2).

### 5.6 Evidence and context builder (`evidence.py`, `context.py`)

- `build_evidence` produces the evidence dict:
  - `query`, `retrieval`, `sources`, `ordering`, `clock_caveat`, `events`, `data_gaps`;
  - gap kinds: `OPAQUE_BYTES`, `UNKNOWN_EVENT_TYPE`, `MALFORMED_PAYLOAD`, `UNMAPPED_ENUM`, `RETRIEVAL_TRUNCATED`, `DUPLICATE_EVENT`;
  - events are **grouped by source**, then sorted by producer timestamp within each source, with no cross-source timeline (deliberate; OPEN_QUESTIONS #6);
  - unknown-type and malformed events also appear in `events`, with `fields = {}`.
- `build_context` renders what the LLM receives, exactly four sections: `USER QUERY`, `DECODED EVENTS`, `DOMAIN KNOWLEDGE`, `DATA QUALITY / DECODING WARNINGS`.
  - Event lines are JSON, labelled `producer_time_ns`.
  - Unknown-type and malformed events appear **only** under data quality.
  - Documents are HTML-escaped, quoted line by line with `| ` and wrapped in `<document …>` tags, after a note that they are data, not instructions.
- A **clock caveat** is added when more than one source is involved.
- **Raw payload bytes never enter the context**, in any encoding (catalogue V01).
- Rendering is a pure function: the same input gives byte-identical context.

### 5.7 LLM synthesis (`synthesis.py`, `llm.py`, `investigate.py`)

The LLM reasons over decoded evidence and domain knowledge only. Its reply must follow the `FailureSynthesis` contract:

```json
{"summary": "…", "likely_cause": "…" or null, "confidence": "low|medium|high",
 "contributing_events": [{"source_id": 0, "timestamp": 0, "event_type": "<event name>"}],
 "uncertainty": ["…"], "data_gaps": ["…"]}
```

- `timestamp` is the producer timestamp in ns.
- `likely_cause: null` means no cause is asserted (the SC6/SC7 negative controls).
- The system prompt (`synthesis.SYSTEM_PROMPT`) is domain-agnostic.

**Progressive investigation (optional):** instead of a synthesis, the LLM may reply with a `context_request`, either `before_event` + `lookback_ns`, or `t_start_ns` + `t_end_ns`. One request is allowed by default.
- `to_retrieval_request` converts it into a `RetrievalRequest`, which applies the contract: a window larger than 1 h is **rejected, not clamped**, and the LLM is told so.
- Overlapping results are merged without duplicates.
- The LLM never gets direct storage access.

**Clients:**
- `StubLLM` is deterministic and offline. Every test uses it, and so does the demo by default.
- `AnthropicLLM` calls Claude (`claude-opus-5-5`, key from `FSS_LLM_API_KEY`). Its output is constrained to the contract's JSON schema, so it cannot send a context request, and live runs use `max_context_requests=0`.

### 5.8 Output validator (`validator.py`)

Runs on every synthesis:

| Rule | Check | On violation |
|---|---|---|
| 1 | Every `contributing_event` exists in the evidence (same source, producer timestamp and event name) | **REJECTED** |
| 2 | `confidence` is low, medium or high | **REJECTED** |
| 3 | `data_gaps` cover every evidence gap (the gap's `event_id`, or "truncated") | Gap restored, flagged |
| 4 | Citations from more than one source come with an uncertainty item mentioning clocks | Clock caveat added, flagged |
| 5 | No citation of an unknown-type or malformed event; summary and likely_cause name no such event, no unconfigured type id and no undecoded bytes | **REJECTED** |
| 6 | Malformed LLM output (or a failed call) | One retry with the error, then a structured `FAILED` result (low confidence, no cause, every gap listed) |

Verdicts: `ACCEPTED`, `ACCEPTED_WITH_CORRECTIONS`, `REJECTED`, `FAILED`. Rules 3-5 are lexical checks. They cannot catch every paraphrase, nor a wrong story built from real events (VERIFICATION_REPORT I3).

### 5.9 Presentation (`presentation.py`, `demo/run_demo.py`)

Every report, in the terminal (`render_investigation`) or as Markdown (`render_markdown`), has eight parts in this order:

1. Question;
2. Retrieval call (sources, window, `max_events`, truncation, follow-up requests);
3. Events, each with its epistemic tag, e.g. `decoded + documented + unknown (8 bytes)`;
4. Data gaps, with uninterpretable data listed as `Uninterpreted data: …`;
5. Retrieved knowledge with provenance;
6. Exact LLM context;
7. Synthesis, with each citation checked against the evidence (`✓ ev-…` or `✗ NOT IN EVIDENCE`);
8. Validator verdict and repairs.

Producer timestamps are shown as UTC and labelled as producer time. `demo/build_outputs.py` writes the reviewer files of `TEST_CASES.md` §15 into `demo/outputs/` from real runs.

## 6. Java core (J1 implemented; J2/J3 design)

| Item | Design |
|---|---|
| Storage | Single file accessed with `FileChannel` positional I/O. Zeroed 64 KiB blocks allocated on demand, one source per block. |
| Framing | `record_len + crc32c + envelope`. A record that doesn't fit goes to a new block; the old block's tail stays zero. |
| Durability | `append()` returns after the write and survives a process crash. `sync()` calls `force(false)` for OS crash and power loss, with group commit. |
| Recovery | Scan each block until `len == 0`, the length overruns the block, or the CRC mismatches. Zero the tail. Rebuild metadata (source, used_len, min/max ts) from the data, never from persisted metadata. |
| Retrieval | J1: full scan with min/max-ts block pruning. J3: time segments by receive time plus per-source block index. |
| Verification | Crash harness: SIGKILL under load (50+ runs), truncation at every offset, bit flips. Invariant: recovered = a valid prefix per source, with no corrupt record ever returned. |

---

## 7. Hard rules: enforcement and tests

| # | Rule (handoff §22) | Enforced by | Tests |
|---|---|---|---|
| 1 | Python never reads Java storage | Retriever interface is the only input | R10 |
| 2 | Java owns retrieval | Contract | J-side |
| 3 | Every retrieval is time-bounded | Retriever validation (both sides) | R01, R02, Y07 |
| 4 | Complete EventRecords, not blocks | Contract | J-side, R-series |
| 5 | Producer timestamp preserved | Decoder copies it unchanged | V06 |
| 6 | No global ordering promised | Downstream sorts for display only | R09, V05 |
| 7 | Payload stays binary until Python decoding | Contract | — |
| 8 | Decoding is deterministic code/config | Decoder | P-series, B-series |
| 9 | LLM never decides offsets, types or endianness | No raw bytes in context | V01 |
| 10 | Unknown event types are not guessed | `UNKNOWN_EVENT_TYPE` | ST03, SC7 |
| 11 | Unknown regions stay opaque | `unknown_bytes` | P08, P09, ST02 |
| 12 | Unknown bytes are not given to the LLM | Evidence builder | V01, V02 |
| 13 | Domain documentation supplies meaning | Enum maps + RAG | E01–E04, K01–K03 |
| 14 | LLM reasons over decoded evidence only | Context builder + validator | Y04 |
| 15 | Cross-source retrieval via ALL | Retriever | R05, SC1–SC5 |
| 16 | Storage internals hidden from Python | Interface | R10 |

---

## 8. Test catalogue

> **`TEST_CASES.md` is now the authoritative catalogue.** It keeps P, S, E, ST, R, V, Y, G, SC and B from this section and adds SPEC, RAG, PI, UI, ARCH and LLM-EVAL. Renamed IDs: the progressive-investigation tests (old Y07) are PI-01 to PI-04; Y07 is now "invalid confidence rejected"; the live evaluation (old Y08) is LLM-EVAL. K01-K04 below are kept as supporting tests.

**Conventions:**
- Unit tests use a stub LLM, so they are deterministic and need no network.
- Live-LLM evaluation is optional (LLM-EVAL).
- Every scenario has golden expected output checked into `tests/golden/`.

### 8.1 Primitive decoding (P)

| ID | Case | Expected |
|---|---|---|
| P01 | Every integer type × {little, big} × {min, 0, max} (48 cases) | Exact values |
| P02 | float32/float64: normal, ±0, ±inf, NaN | Valid JSON output; documented policy for non-finite values plus a warning |
| P03 | boolean bytes 0x00, 0x01, 0x02 | false, true, documented policy (warning on non-canonical) |
| P04 | Field ending exactly at the payload end | SUCCESS |
| P05 | Payload one byte short of the last field | MALFORMED_PAYLOAD; reason names the field and byte ranges |
| P06 | Zero-length payload, schema with zero fields | SUCCESS |
| P07 | Zero-length payload, schema with fields | MALFORMED_PAYLOAD |
| P08 | Gap of 3 bytes between fields | PARTIALLY_DECODED, unknown_bytes = 3 |
| P09 | 8 trailing opaque bytes | PARTIALLY_DECODED, unknown_bytes = 8 |
| P10 | 64 KiB payload with fields near the end | Correct values, no slowdown |

### 8.2 Schema validation (S)

| ID | Case | Expected |
|---|---|---|
| S01 | Overlapping fields | Load error naming both fields |
| S02 | `uint32` declared with size 2 | Load error |
| S03 | Unknown type `uint24` | Load error |
| S04 | Negative offset | Load error |
| S05 | Duplicate field name | Load error |
| S06 | Same event_type in two files | Load error |
| S07 | `endian: middle` | Load error |
| S08 | Enum on a float field | Load error |
| S09 | YAML with `!!python/object` tag | Rejected; nothing executed |
| S10 | Empty schema pack | Loads; every event is UNKNOWN_EVENT_TYPE |
| S11 | Offset 2^40 | Load error or MALFORMED; never an overflow or crash |

### 8.3 Enums (E)

| ID | Case | Expected |
|---|---|---|
| E01 | Mapped value 17 | `status_name = LIDAR_TIMEOUT` |
| E02 | Unmapped value 99 | `UNKNOWN`, raw 99 kept |
| E03 | Enum on a signed field, value −1 | Correct lookup |
| E04 | Edit the enum map in YAML only | Output changes with no code change |

### 8.4 Status aggregation (ST)

| ID | Case | Expected |
|---|---|---|
| ST01 | Full coverage | SUCCESS, unknown_bytes = 0 |
| ST02 | Fields plus opaque tail | PARTIALLY_DECODED |
| ST03 | Unknown type 0x31 | UNKNOWN_EVENT_TYPE, `fields = {}` |
| ST04 | Truncated field | MALFORMED_PAYLOAD with reason |
| ST05 | Opaque tail **and** truncated field | MALFORMED_PAYLOAD (precedence) |

### 8.5 Retrieval contract (R)

| ID | Case | Expected |
|---|---|---|
| R01 | Missing start or end | Rejected |
| R02 | `t_end <= t_start` | Rejected |
| R03 | Events exactly at t_start and t_end | Included and excluded respectively (half-open; or documented) |
| R04 | Single source filter | Only that source |
| R05 | `source = ALL` | All sources in the window |
| R06 | event_type filter | Only that type |
| R07 | 500 matching, max_events = 100 | Exactly 100, `truncated = true` |
| R08 | Empty window | `[]`, `truncated = false` |
| R09 | Shuffle retriever output order | Identical evidence JSON downstream |
| R10 | Static check | Decoder, evidence and synthesis modules have no file or storage access |

### 8.6 Evidence builder (V)

| ID | Case | Expected |
|---|---|---|
| V01 | Search the context for raw payload bytes (hex/base64) | Not found |
| V02 | Unknown type present | Listed in data gaps only |
| V03 | Partial event | Gap entry with byte count |
| V04 | Malformed event | Gap entry with reason |
| V05 | 1 source vs 2+ sources | Clock caveat absent vs present |
| V06 | Timestamps | Labelled as producer time, values unchanged |
| V07 | Same input twice | Byte-identical context |
| V08 | Domain document containing "ignore previous instructions" | Delimited as data; validator still enforces the contract |

### 8.7 Domain knowledge / RAG (K)

| ID | Case | Expected |
|---|---|---|
| K01 | Code with an enum map | Resolved in the decoder, not by RAG |
| K02 | Evidence containing LIDAR_TIMEOUT | Matching document retrieved |
| K03 | Value with no documentation | Marked undocumented; no explanation |
| K04 | D2 scenario with all domain docs loaded | No drone documents retrieved |

### 8.8 Synthesis and validator (Y), stub LLM

| ID | Case | Expected |
|---|---|---|
| Y01 | Well-formed output | Passes the schema |
| Y02 | Stub cites an event not in the evidence | Rejected and flagged |
| Y03 | Stub omits a known data gap | Flagged; gap restored |
| Y04 | Stub interprets opaque bytes or an unknown type | Flagged |
| Y05 | Cross-source causal claim without a clock caveat | Flagged |
| Y06 | Stub returns invalid JSON | One retry, then a structured failure; no crash |
| Y07 | `confidence: "very high"` | Rejected (now; formerly the context-request case, see PI-01..04) |
| LLM-EVAL | *(Optional, live LLM)* SC1–SC8 | Outputs saved to `demo/outputs/live/` for review (formerly Y08) |

### 8.9 Generalisation (G)

| ID | Case | Expected |
|---|---|---|
| G01 | Five domain packs (D1–D5) through the same pipeline | All pass with zero code change |
| G02 | grep core package for `drone\|lidar\|uav\|formation` | No matches outside packs, examples and tests |
| G03 | D4 big-endian pack alongside little-endian packs | Both decode correctly |
| G04 | Drop a new pack directory in | Discovered and loaded with no registration code |

### 8.10 End-to-end scenarios (SC): mock retriever → decoder → evidence → stub synthesis

| ID | Domain | Story | What it proves |
|---|---|---|---|
| SC1 | D1 | 298 LiDAR timeout → 474 avoidance → leaves formation; one diagnostic has 8 opaque bytes | Cross-source cause, gap reported, clock caveat |
| SC2 | D2 | DB pool exhausted → order-service p99 spike → payment-service 504s | The failing service is not the cause; retrieval with ALL is needed |
| SC3 | D3 | Temp sensor drift on A → overheat interlock → conveyor B starved; vendor PLC sends unknown type 0x7F | Unknown event preserved and reported, not guessed |
| SC4 | D4 | Wheel-speed ECU fault → ABS disabled → dash warning; one frame truncated | Big-endian decoding, malformed handling |
| SC5 | D5 | AGV-12 battery critical → AGV-7 replans; **AGV-7's clock is skewed earlier** | Must not infer causation from timestamps; uncertainty stated |
| SC6 | Any | Window with only normal events | "No failure evidence found", low confidence, no invented cause |
| SC7 | Any | Window with only unknown event types | Evidence uninterpretable; no cause asserted |
| SC8 | Any | Retrieval truncated at max_events | "Retrieval truncated" reported as a data gap |

### 8.11 Robustness and properties (B)

| ID | Case | Expected |
|---|---|---|
| B01 | Hypothesis: random bytes against every schema | Never raises; status always valid |
| B02 | Every truncation length 0..len of each golden payload | Never SUCCESS below the required length |
| B03 | Random valid schemas × random payloads | Invariants: SUCCESS ⇒ unknown_bytes = 0; decoded fields ≤ schema fields |
| B04 | Decode 100k events | Throughput (events/s) recorded on EC2 |
| B05 | Same seed, same run | Identical outputs (determinism) |

### 8.12 Recommended professor demo (about 10 minutes)

1. **SC2 (microservices).** Shows the system isn't drone-specific and that the visible failure isn't the cause.
2. **SC1 (drones).** The original problem statement, including the opaque-bytes gap.
3. **SC5 (clock skew).** The system refuses to over-claim causality.
4. **SC6 and SC7 (negative controls).** No invented failures.
5. **Y02 (hallucinated citation caught).** The validator in action.
6. **G01 (domain swap).** The same code with a different YAML pack.

---

## 9. How to run *(commands confirmed by verification run 2 on EC2, Python 3.14.4)*

```bash
cd ~/fss
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                        # pinned; add requirements-app.txt for --live / Streamlit
pytest -q                                              # 501 passed, 8 skipped (live) in ~10 s
pytest --cov=fss_py --cov-branch --cov-report=term-missing   # coverage (96.2 % line / 91.5 % branch)
pytest -s -k RAG04_gold                                # prints RAG precision@k / recall@k on tests/rag_gold.yaml
pytest -s -k B04                                       # prints decode throughput
python fixtures/generate_fixtures.py --check           # golden fixtures and contract vectors current
python -m scenarios.generate --check                   # scenario .bin files and tests/golden current
python demo/run_demo.py SC2 SC1 SC5 SC6 SC7 Y02 G01     # readable demo output (stub LLM); see DEMO.md
python demo/build_outputs.py                           # TEST_CASES §15 files → demo/outputs/
python demo/build_outputs.py --junit J.xml --coverage C.json   # … plus summary.md from a test run
python -m fss_py --fixture fixtures/golden/scenario_298_474.bin \
    --start 2026-10-08T10:07:00Z --end 2026-10-08T10:07:10Z      # evidence JSON from the CLI
pip install -r requirements-app.txt                    # optional: anthropic SDK for the live LLM
FSS_LLM_API_KEY=… pytest -m live                       # optional live smoke test (LLM-EVAL)
FSS_LLM_API_KEY=… python -m scenarios.llm_eval --runs 3 --out demo/outputs/live   # LLM-EVAL-1..7
python demo/build_outputs.py --junit J.xml --coverage C.json --llm-eval demo/outputs/live/llm_eval.md
FSS_LLM_API_KEY=… python demo/run_demo.py SC1 --live    # one scenario with Claude
```

## 10. Verification record *(filled by the verification runs, 2026-10-09)*

Full details are in `VERIFICATION_REPORT.md`. The code as received is commit `68f3123`. Run 1 ended at `3c2b8c5` (catalogue of §8). Run 2 ran at `70285bd` (the `TEST_CASES.md` catalogue).

### Run 2 (`70285bd`)

| Area | Result | Notes |
|---|---|---|
| Environment | EC2 Ubuntu 26.04 LTS, 8 vCPU; Python 3.14.4; fresh venv from pinned requirements; no Java process | MockRetriever and fixtures only |
| Tests | 509 cases: 501 passed, 0 failed, 0 xfail, 8 skipped (live, no key) | All 123 non-live `TEST_CASES.md` IDs PASS |
| Spec conformance | SPEC-01..24 PASS | SPEC-23 envelope part justified (Java-side) |
| RAG conformance | RAG-01..14 PASS (14/14) | Gold set: P@3 0.913, R@3 0.955; P@5 0.890, R@5 1.000. RAG-01: 109/109 decoded events identical without the corpus |
| Coverage, branch | decoder 95.8 %, schema 87.5 %, knowledge 92.5 %, evidence 100 %; total 96.2 % line / 91.5 % branch | Required ≥ 85 % on the four modules |
| B04 throughput | 97 447 / 96 882 / 97 290 events/s (three runs) | |
| Demo | `run_demo.py SC1 SC2 SC5 SC6 SC7 Y02` exit 0, empty stderr, 514 lines | ACCEPTED ×5, Y02 REJECTED (rule 1) |
| LLM-EVAL-1..7 | Not run: no `FSS_LLM_API_KEY` | Metric code unit-tested on stub runs |
| Bugs in team code | None | |
| New deviations | D10 no token budget; D11 isolation by relevance, not domain filter; D12 "Uninterpreted data" wording; D13 SPEC-23 envelope out of Python scope | |

### Run 1 (`3c2b8c5`)

| Area | Result | Notes / deviations from spec |
|---|---|---|
| Environment (instance, Python version) | EC2 Ubuntu 26.04 LTS, 8 vCPU, 31 GiB; Python 3.14.4; fresh venv from pinned `requirements.txt` | The code was in `~/minor`, not `~/fss`; it was imported unchanged into a new git repo `~/fss` |
| Existing tests (count / pass) | 171 / 171 | Still 171/171 after the run. Only change to existing tests: two static-check allowlists accept the new configuration loaders. |
| Catalogue tests added (count / pass) | 77/77 IDs, 198 cases: 190 pass, 0 fail, 0 xfail, 8 skipped (Y08 live, no key) | Plus 84 supporting tests. Total: 445 passed, 8 skipped. |
| Coverage (line / branch) | Before: 86.4 % / 85.4 %. After: 96.2 % / 92.0 %. | Branch coverage, decoder / schema / evidence: 95.8 / 87.5 / 100 % (required ≥ 85 %) |
| Traceability: handoff §2-23 | As received: §15, §16, §17, §21 ❌; §20, §23 partial | After the run: all ✅. §15-§17, §20-§21 and §5.8 were implemented by the verification run (needs team review) |
| Hard rules 1-16 | All 16 have passing tests | Rules 13 and 14 were only partly testable as received (no RAG, no LLM) |
| Generalisation G01-G04 | All pass | G02: 3 hits in core (`cli.py:6`, `cli.py:37`, `schema.py:81`), removed by a pure refactor; the default schema moved to `[tool.fss]` |
| Policy decisions (§5.3) | Timestamps: u64 ns. Interval: half-open. Malformed: all-or-nothing. NaN/inf: JSON strings plus a warning. Non-canonical bool: whole event MALFORMED. | No raw payload bytes reach the LLM context. The one exception: the bool reason quotes that single byte's value. |
| Bugs found and fixed | None in team code | No catalogue test failed against the received code |
| B04 throughput | ≈ 96 000 decoded events/s (100 000 events, all five domains, one core) | |
| Demo | `run_demo.py SC1 SC2 SC5 SC6 SC7 Y02` exit 0, no stderr | Y02 → REJECTED (rule 1) |
| Open issues | (1) new modules need team review; (2) live LLM never exercised; (3) validator rules 3-5 are lexical; (4) YAML 1.1 ints (`010` → 8) accepted silently; (5) progressive retrieval tested with the stub only | Ranked list: VERIFICATION_REPORT.md |

## 11. Limitations and next steps

- **Java core:** J1 (store + crash harness) is done; J2 concurrent ingest → J3 segments/index → I1 Java↔Python transport is the critical path.
- **Live LLM:** the synthesis stage has only been exercised with the stub LLM; run LLM-EVAL (`python -m scenarios.llm_eval --runs 3`) and review the outputs before relying on live explanations.
- **RAG:** exact-term retrieval with a chunk-count budget only; no token budget and no domain filter (D10, D11).
- **No public dataset** contains labelled cross-source failure chains. Scenario packs are synthetic; real logs (PX4 Flight Review, ALFA, RflyMAD) are for decoder realism and single-source evaluation.
- **Producer clocks are not synchronised**, so causal claims across sources remain probabilistic and are always reported with uncertainty.
- **Durability scope:** process crash is guaranteed; OS crash or power loss is best-effort through `force()` with group commit, and cannot be tested on EC2.
