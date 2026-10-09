# Failure Synthesis System: Crash-Tolerant Evidence Preservation and Bounded, Knowledge-Grounded Failure Explanation for Distributed Event-Producing Systems

**Draft v0.1, 9 October 2026.** Minor Project, Department of Computer Science & Engineering, Punjab Engineering College, Chandigarh.
Team: Arnav Sachdeva, Kritansh Uppal, Sumit Rai, Vibhanshu *(edit as appropriate)*.

> **Status of this draft (updated 9 October 2026 after verification run 2).** Sections 1–6 and 8–10 describe the problem, design, generalisation, drone case study and real-world context. Section 7.4 is now filled **only** from the Python-layer verification run of 9 October 2026 (commit `70285bd`; `VERIFICATION_REPORT.md`, `TEST_CASES.md`, `demo/outputs/summary.md`). The live-LLM metrics were **not run** (no API key) and are marked so. Where §4 described the design differently from the code, the text now follows the code and notes the deviation (`VERIFICATION_REPORT.md` D-numbers). The Java storage core is being implemented separately by a teammate; its design is described here and its evaluation is future work until it lands. Bibliographic details previously marked **[verify]** were checked against Crossref, DBLP/DOAJ or the publisher on 9 October 2026; none remain.

---

## Abstract

When a distributed system fails, the component that shows the failure is often not the one that caused it. The evidence needed to explain the failure is spread across many producers, recorded with unsynchronised clocks, encoded in heterogeneous binary formats, and at risk of being lost if the central logging process itself crashes.

We present the **Failure Synthesis System (FSS)**, a domain-agnostic pipeline that combines four ideas:

- **Crash-tolerant evidence preservation.** An append-only, CRC-framed block store whose recovery yields a valid prefix of acknowledged events.
- **A bounded, cross-source retrieval contract.** Every query names a finite time window and may span all sources.
- **Deterministic, schema-driven interpretation.** Binary payloads are decoded only by configured schemas, with an explicit three-level epistemic model: *decoded*, *documented*, *unknown*.
- **Knowledge-grounded LLM synthesis.** Retrieval-augmented domain knowledge feeds the LLM, whose structured output is checked by a validator against the evidence it was given.

The language model never sees raw bytes, never decides offsets, types or endianness, and is not allowed to turn unknown data into confident claims. We show how one implementation covers drone fleets, microservices, industrial lines, vehicle networks and warehouse robots through configuration alone. We then give a detailed case study for multi-drone fleets, including a survey of drone logging standards and public flight-data sets. That survey finds no IEEE standard that defines an onboard event-log format, and no public dataset with labelled cross-agent failure chains. We define an evaluation methodology with 130 catalogue test IDs and live-LLM metrics for attribution accuracy, citation validity, preservation of unknowns, and clock humility. On the Python layer, with a mock retriever and a stub LLM, all 123 non-live test IDs pass (509 test cases: 501 passed, 8 live cases skipped), retrieval reaches precision@3 = 0.913 on a 25-query gold set, and the decoder sustains about 97,000 events/s. The live-LLM metrics have not yet been run.

---

## 1. Introduction

### 1.1 Motivation

Modern systems are made of many independent event producers: microservices, PLCs on a production line, ECUs in a vehicle, robots in a warehouse, drones in a formation. Each continuously emits telemetry: state updates, sensor readings, warnings, faults. When something goes wrong, three practical difficulties appear together.

1. **The symptom and the cause live in different sources.** In the AWS Kinesis event of 25 November 2020, a capacity addition to the Kinesis front-end fleet pushed servers past an operating-system thread limit. The *visible* impact appeared in Cognito, CloudWatch, Lambda, Auto Scaling, EventBridge, ECS and EKS, each through its dependency on Kinesis or on a service that depended on Kinesis [R1]. Looking only at the logs of the service that visibly failed would have missed the cause. Our running drone example has the same shape: Drone 474 leaves formation, but the triggering event is a LiDAR timeout on Drone 298.

2. **The evidence layer can fail at the worst moment.** In the same AWS event, CloudWatch could not persist all metric data, alarms became unreliable, and the status-dashboard tool was itself affected [R1]. A logging system whose own crash destroys or corrupts recent evidence fails exactly when it is needed. Events held only in memory, or partially written when the process dies, must be either preserved or detectably discarded. They must never be silently corrupted.

3. **Raw telemetry cannot be safely "read" by a language model.** Large language models are increasingly used for log analysis and root-cause analysis [R12–R15]. But telemetry in autonomous and embedded systems is mostly **binary**: offsets, integer widths, float formats, endianness and bit flags. A model asked to guess what bytes 4–7 mean can produce a fluent, confident, wrong answer. Even with decoded values, the model may give an undocumented code a plausible but invented meaning.

### 1.2 Approach

FSS separates *what evidence exists* from *what it means* and from *what probably happened*:

```
Producers → [Evidence layer: ingest → durable store → recovery → bounded retrieval]
          → [Interpretation layer: schema decoding → documented semantics (RAG)]
          → [Reasoning layer: LLM synthesis → validator] → Investigator
```

Each boundary carries a rule:
- The evidence layer never interprets payloads.
- The interpretation layer is deterministic and configuration-driven.
- The reasoning layer sees only decoded evidence and documented knowledge, and must report what it cannot know.

### 1.3 Contributions

- **C1: An epistemic separation for failure explanation.** Every fact presented to the reasoning layer is labelled as *decoded* (deterministic from bytes), *documented* (meaning from configured enums or retrieved domain documents) or *unknown* (unconfigured types, opaque regions, malformed fields, undocumented values). Unknowns are carried through to the output as explicit data gaps.
- **C2: A bounded, cross-source retrieval contract.** `retrieve(source | ALL, t_start, t_end, event_type?, max_events)`. It makes cross-agent investigation possible while preventing unbounded history scans, including scans requested by the LLM during progressive investigation.
- **C3: A crash-tolerant block-store design.** Fixed 64 KiB single-source blocks, per-record CRC framing, no record crossing a block boundary, and recovery that rebuilds metadata from data. The invariant: after any process crash, each source's recovered events are a valid prefix of its acknowledged events.
- **C4: A validator-enforced synthesis contract.** A structured output (summary, likely cause, confidence, contributing events, uncertainty, data gaps) checked against the evidence actually supplied. Fabricated citations, omitted gaps, interpretations of unknown data and unhedged cross-clock causal claims are rejected.
- **C5: Domain generalisation and a drone case study.** One code base instantiated for five domains by configuration alone. A detailed study of drone fleets maps MAVLink/ULog/DataFlash telemetry onto FSS, surveys IEEE/ASTM standards and public datasets, and identifies the missing benchmark of labelled cross-agent failures.

---

## 2. Background and related work

### 2.1 Durable logs and crash consistency

Write-ahead logging and redo-based recovery are classical (ARIES [R2]). Pillai et al. showed that application-level crash consistency depends on subtle, file-system-specific persistence properties. Their ALICE tool found 60 vulnerabilities across 11 widely used systems [R3]. The practical lesson for FSS is to avoid relying on writes being atomic or ordered, and to *test* recovery by exploring crash states.

LevelDB's log uses 32 KB blocks of records, each with a checksum, length and type header. Records may be fragmented across blocks (FIRST/MIDDLE/LAST), and readers resynchronise at block boundaries after corruption [R4]. Kafka organises topics as segmented append-only logs with a CRC per message and relies on the OS page cache [R5]. MCAP, a container format for robotics pub/sub data, stores messages in chunks annotated with start/end times and CRCs, writes a summary index at the end, and can rebuild that index from a truncated file [R6].

**FSS's block store** sits in this family. Its one deliberate difference from LevelDB is that records are *never* fragmented: if a record doesn't fit, the remainder of the block stays empty. This trades some space for simpler scanning and recovery.

### 2.2 Log analytics data

Loghub collects 19 real-world log datasets from distributed systems, supercomputers, operating systems, mobile systems, server applications and standalone software. It is widely used for log parsing and anomaly-detection research [R7]. These are mostly **text** logs from single systems. They are useful for evaluating text-log methods but contain neither binary payloads nor labelled cross-source causal chains.

### 2.3 LLMs for log analysis and root-cause analysis

- **LogPrompt** shows that prompt strategies let LLMs perform zero-shot, interpretable log parsing and anomaly detection [R12].
- **LogGPT** explores ChatGPT for log-based anomaly detection on BGL and Spirit [R13].
- **RCACopilot** splits RCA into a deterministic diagnostic-collection stage and an LLM stage that predicts a root-cause category with an explanation. It reports accuracy up to 0.766 on a year of Microsoft incidents [R14].
- **RCAEval** provides three datasets with 735 failure cases from microservice systems, plus 15 reproducible RCA baselines [R15].

FSS follows RCACopilot's two-stage idea of collecting deterministically and then reasoning. It differs in three ways: (i) evidence is **binary and multi-source** with unsynchronised clocks; (ii) **decoding is removed from the model entirely**; (iii) the output is **validated** against the supplied evidence, and unknowns are carried through as first-class content.

### 2.4 Retrieval-augmented generation

RAG conditions a generator on documents retrieved from a non-parametric memory [R16]. In FSS, RAG supplies *documented meaning*: error-code descriptions, state definitions, failure modes and manuals. It is never used for decoding. We also put deterministic enum maps *ahead of* RAG, so that a code's meaning is resolved exactly whenever a mapping exists.

### 2.5 Drone telemetry, logging and forensics

Drone forensics research has repeatedly had to reverse-engineer proprietary, encrypted flight logs. One example is the DROP parser for DJI Phantom III DAT files [R8]. Surveys note that vendor-specific methods generalise poorly [R9]. Recent work localises problems inside text flight-log messages for root-cause attribution [R10]. Public fault datasets exist for single vehicles: ALFA (real fixed-wing flights with ground-truth fault timing) [R17] and RflyMAD (11 multicopter fault types across SIL, HIL and real flights) [R18].

### 2.6 Positioning

| Capability | Log stores (Kafka, LevelDB-style) | Robotics containers (MCAP, ULog) | Text-log LLM methods (LogPrompt, LogGPT) | LLM RCA (RCACopilot) | **FSS** |
|---|---|---|---|---|---|
| Crash-recovery semantics | ✔ | partial (index recovery) | – | – | ✔ (design) |
| Binary payloads | opaque | self-describing | – | – | schema-driven |
| Bounded cross-source retrieval | by offset/topic | by time/channel | – | handler-driven | ✔ contract |
| Deterministic decoding before the LLM | – | – | n/a (text) | partial | ✔ enforced |
| Explicit unknowns in output | – | – | – | – | ✔ |
| Output validated against evidence | – | – | – | – | ✔ |

---

## 3. Problem formulation

**Sources and events.** Let *S* be the set of event producers. An event is

  *e = (s, t, τ, p)*, with *s ∈ S*, *t* the producer timestamp (in the producer's own clock), *τ* the event type, and *p* the payload bytes.

The system makes **no assumption** that producer clocks are synchronised, or that *t* gives a global causal order across sources (cf. Lamport [R11]).

**Store and retrieval.** The evidence layer persists events. A query is

  *q = (S_q, [a, b), τ_q, k)*, with *S_q ⊆ S* or *S_q = ALL*, a **finite** interval [a, b) over producer time, an optional type filter, and a result cap *k*.

The result is *R(q)*, a set of complete events satisfying the predicates, together with a flag saying whether the cap truncated it. No ordering is promised.

**Interpretation.** A schema pack Σ maps event types to field layouts. Decoding is a total, deterministic function

  *D_Σ(e) → (fields, status, unknown_bytes, warnings)*, with status ∈ {SUCCESS, PARTIALLY_DECODED, UNKNOWN_EVENT_TYPE, MALFORMED_PAYLOAD}.

An enum map *M* assigns documented names to some codes. A knowledge corpus *K* supplies prose meaning.

**Synthesis.** Given an investigator question *Q*, evidence *E = D_Σ(R(q))*, enum names from *M* and retrieved knowledge *K_q*, produce *Y = (summary, likely_cause, confidence, contributing_events, uncertainty, data_gaps)*.

**Requirements.**

| # | Requirement |
|---|---|
| R1 Durability | After a crash of the central process, every acknowledged event is recoverable, and no corrupt record is ever returned. |
| R2 Boundedness | Every retrieval, including any requested during reasoning, specifies a finite window and a cap. |
| R3 Cross-source | A query may span all sources, so causes outside the symptomatic source can be found. |
| R4 Determinism | Interpretation of bytes depends only on Σ and *M*: the same input gives the same output. |
| R5 Epistemic honesty | Every statement in *Y* is supported by decoded or documented evidence. Unknown data appears only in data_gaps. |
| R6 Clock humility | Causal claims across sources are qualified, because producer clocks are unsynchronised. |
| R7 Domain independence | A new domain is added through Σ, *M* and *K* alone, with no code change. |

---

## 4. System design (general case)

### 4.1 Architecture

```
┌──────────── Evidence layer (Java) ─────────────┐   ┌────────────── Interpretation + reasoning (Python) ──────────────┐
│ TCP ingest → envelope validation → bounded     │   │ Retriever client → schema lookup → deterministic decoder →      │
│ queue → single writer → block store (CRC)      │──▶│ enum resolution → evidence builder ⇄ knowledge (RAG) →          │
│ → recovery → bounded retrieve()                │   │ LLM synthesis → validator → presentation                        │
└────────────────────────────────────────────────┘   └─────────────────────────────────────────────────────────────────┘
          EventRecord {source_id, timestamp, event_type, payload_bytes} + truncated flag
```

**The boundary:** the evidence layer decides *what evidence exists* and returns it correctly. The interpretation layer decides *how it is interpreted and explained*. Python never reads storage files. Java never interprets payloads.

### 4.2 Envelope and contract

The ingest envelope carries the minimal metadata the store needs: source id, producer timestamp, event type, payload length and payload. Its byte layout is configurable per deployment (NFR-08). The v0 layout we use is:

```
magic u16 | version u8 | flags u8 | source_id u32 | timestamp_ns u64 | event_type u32 | payload_len u32 | payload
```

### 4.3 Crash-tolerant storage and recovery (design)

- **Blocks.** Storage is divided into fixed 64 KiB blocks, zero-preallocated, each owned by one source. Records are framed as `record_len u32 | crc32c u32 | envelope`. A record never crosses a block boundary; if it doesn't fit, the remaining space stays zero and the record goes into the source's next block.
- **Segments.** Blocks are grouped into time segments by **receive time**, because receive time is monotonic at the central node. Each block and segment also records the **min/max producer timestamp** it contains, so queries over producer time can prune safely despite skew. Only the *active* segment can have a torn tail; sealed segments carry a CRC-protected index.
- **Recovery.** For each block, scan from offset 0 until `record_len == 0`, the length overruns the block, or the CRC mismatches. Zero the tail. Rebuild block metadata from the surviving records rather than trusting persisted metadata. Sealed-segment indexes are trusted only if their CRC verifies; otherwise they are rebuilt by scan.
- **Invariant.** For every source, the recovered events form a prefix of that source's acknowledged sequence, and no record with a bad checksum is ever returned.
- **Durability point.** `append()` survives a process crash once the write has returned. Surviving an OS crash or power loss needs `force()`, amortised by group commit. The project's guarantee is process-crash durability. Power loss is best-effort and outside what can be tested on cloud VMs.

### 4.4 Bounded, cross-source retrieval

```
retrieve(source_id | ALL, t_start, t_end, event_type?, max_events) → EventRecord[] , truncated
```

**Internally:**
1. Select the segments whose producer-time range overlaps the query.
2. For each requested source, take its block list.
3. Prune blocks by min/max producer time.
4. Scan the remaining blocks sequentially and filter exactly.

This replaces per-event indexing with "narrow, then scan". **Unbounded queries do not exist in the API.** The bound protects storage performance and stops the reasoning layer from pulling the whole history into a prompt.

### 4.5 Schema packs and the deterministic decoder

A **schema pack** is a directory of YAML schema files plus a `docs/` directory of domain documents. Each file has a `schema_set` name, named `enums`, and `event_types: {id: {name, version, fields}}`. Each field gives a name, offset, primitive type (`u8`…`u64`, `i8`…`i64`, `f32`, `f64`, `bool`), size, endianness (`little` by default, or `big`) and, optionally, a named enum plus the name of the field that receives its label (`enum`, `enum_field`).

*Deviation note.* Earlier drafts used the type names `uint8…`, `float32`, `boolean` and a one-event-per-file layout with inline enums. The code accepts neither: `uint32` is rejected as an unknown type, and the old layout fails with "unknown key(s)" (`VERIFICATION_REPORT.md` D2, D3). Appendices B and C now show the real format.

Packs are validated at load time: overlaps, size/type mismatches, unknown types, negative or overflowing offsets, duplicate names or types, invalid endianness, and enums on non-integers are all rejected. A safe YAML loader is used.

**Decoding algorithm:**

```
decode(e):
  schema ← Σ[e.event_type]
  if schema is None: return UNKNOWN_EVENT_TYPE, fields={}   # bytes stay in the store only
  covered ← ∅
  for f in schema.fields (by offset):
      if f.offset + f.size > len(e.payload): return MALFORMED_PAYLOAD(reason=f, needed, available), fields={}
      v ← unpack(e.payload[f.offset : f.offset+f.size], f.type, f.endian)
      if f.type = bool and v ∉ {0,1}: return MALFORMED_PAYLOAD(reason), fields={}
      fields[f.name] ← v ; covered ← covered ∪ [f.offset, f.offset+f.size)
      if f.enum: fields[f.enum_field] ← f.enum.get(v) or ("UNKNOWN" + warning)
  u ← len(e.payload) − |covered|
  return (u > 0 ? PARTIALLY_DECODED : SUCCESS), fields, unknown_bytes=u
```

Status precedence: MALFORMED > UNKNOWN_EVENT_TYPE > PARTIALLY_DECODED > SUCCESS. The three policies the design left open are now fixed by the code and tested:

- **Non-finite floats** (NaN, ±inf) are kept, with one warning per field, and serialised as the strings `"NaN"`, `"Infinity"`, `"-Infinity"` (P02).
- **A non-canonical boolean** (a byte other than 0 or 1) makes the whole event `MALFORMED_PAYLOAD` (P03; deviation D8 from a warn-and-coerce reading).
- **Fields before a malformed field are discarded.** Decoding is all-or-nothing: `MALFORMED_PAYLOAD` carries no values (P05, ST05).

### 4.6 The three epistemic levels

| Level | Origin | Example | Allowed use in synthesis |
|---|---|---|---|
| **Decoded** | Deterministic decoding of bytes | `active_conns = 50` | Factual evidence |
| **Documented** | Enum map or retrieved domain document, with provenance | `17 = LIDAR_TIMEOUT`; "a LiDAR timeout means the expected scan was not received in time" | Documented meaning |
| **Unknown** | Unconfigured type, opaque bytes, malformed field, unmapped or undocumented value | "8 bytes not configured" | **Only** as a data gap |

Keeping these levels separate is what lets FSS say both *what it believes happened* and *where its evidence ends*.

### 4.7 Knowledge layer (RAG)

The knowledge corpus holds error-code tables, protocol documents, manuals, state descriptions, architecture documents and failure-mode documents. Its design rules are:

- **Deterministic first.** Codes with an enum mapping are resolved in the decoder; RAG never overrides that mapping. If retrieved documents and the map disagree, both are shown with provenance and a conflict warning.
- **Evidence-driven queries.** Retrieval queries are built from the decoded evidence (event types, enum names, states present) together with the investigator's question, not from the question alone.
- **Provenance.** Every snippet in the context carries its document and chunk id and is tagged *documented*.
- **Bounded context.** A top-k chunk budget caps knowledge volume (default 8). Truncation is reported as a data-quality note. *Deviation (D10):* there is no token budget; the cap counts chunks.
- **Absence is information.** A value with no documentation is marked *undocumented*; the model is told not to explain it. If nothing matches, the context says that no domain documentation was found.
- **Conflicts are shown, not resolved.** If two documents, or a document and the enum map, give different meanings for a code, every claim is shown with its source and a conflict warning.
- **Isolation by relevance.** A chunk is a candidate only if it explains a term present in the evidence, so drone manuals do not enter a microservice investigation even when every domain's documents are loaded (RAG-10). *Deviation (D11):* each chunk records its domain as provenance, but the domain is not used as a filter.

**Implementation.** Retrieval is deterministic exact-term matching, with no embeddings and no vector store. Documents are Markdown with front matter: `title`, `kind` (one of six), `keys` (the event names and labels the document explains) and, optionally, `codes` (document-defined code meanings, e.g. `planner_state 4 → AVOIDANCE_MANEUVER`). Each document is split into paragraph chunks with id `doc#n`. Candidates come only from evidence terms (event names, documented labels) or code values present in the evidence. The investigator's question only re-ranks them. A document's evidence matches give each of its chunks a base score (10 per documented label, 5 per event name, 5 per document-defined code); each question word found in the chunk, its title or keys adds 1. Ties are broken by document id, then chunk number, so the same evidence always gives the same chunks in the same order (RAG-06).

### 4.8 Evidence context, synthesis and validation

The model receives exactly four parts:
1. the question;
2. decoded events, one JSON object per line: `event_id`, `source_id`, `producer_time_ns`, event name, type id, status, then the values split into `decoded` and `documented` groups. Events are grouped by source and ordered by producer time within a source; no order across sources is implied. *Deviation (D5):* this replaces a single cross-source timeline. Events of unknown type or with malformed payloads are listed only in the data-quality part;
3. domain knowledge, each chunk wrapped as `<document id chunk kind domain tag="documented">` and quoted line by line, so a document cannot forge a section header (RAG-13); code meanings defined by documents are listed with their source;
4. data quality: decoding gaps, undocumented values, knowledge conflicts, knowledge and retrieval truncation, and a clock caveat whenever more than one source is involved.

Each part opens with a note stating its epistemic level (decoded, documented, unknown).

Raw payload bytes never appear in any form.

The output contract is:

```json
{"summary": "...", "likely_cause": "...", "confidence": "low|medium|high",
 "contributing_events": [{"source_id": 298, "timestamp": 0, "event_type": "LIDAR_STATUS"}],
 "uncertainty": ["Producer clocks are not guaranteed to be synchronised."],
 "data_gaps": ["One diagnostic payload contained 8 uninterpreted bytes."]}
```

`likely_cause` may be `null` when no cause is asserted (negative controls; deviation D9).

The **validator** (rule numbers as in the code):
1. rejects the answer if a contributing event is not in the evidence (matched on source, producer timestamp and event name);
2. rejects a confidence outside low / medium / high;
3. restores any decoder-reported gap the model omitted;
4. adds a clock caveat to claims that cite more than one source;
5. rejects answers that rest on uninterpretable data (citing an unknown-type or malformed event, or naming undecoded bytes);
6. retries once on malformed output, then returns a structured failure.

Verdicts are ACCEPTED, ACCEPTED_WITH_CORRECTIONS (rules 3, 4), REJECTED (rules 1, 2, 5) and FAILED (rule 6). The rules are lexical checks; §9 discusses what they cannot catch.

### 4.9 Progressive investigation

The model may ask for more context ("what happened on all sources in the 30 s before this event?"). Such requests are translated into new **bounded** `retrieve()` calls. The policies, as implemented:

- **Rounds:** one extra request per investigation by default (`max_context_requests = 1`). After that the model must answer.
- **Windows:** at most one hour; larger or "all history" requests are **rejected, not clamped**. The model is told why and must answer from what it has (PI-02, PI-03).
- **Anchors:** a "before event X" request must name an event that is in the evidence.
- **Volume:** the same `max_events` as the first query; truncation is reported as a data gap.
- **Same path:** returned events go through the same decoder, evidence builder and knowledge lookup (PI-05). The model never gets direct storage access.

This path is tested with the stub LLM only. The live client currently constrains output to the synthesis schema, so live runs use `max_context_requests = 0` (`VERIFICATION_REPORT.md` I5).

### 4.10 Presentation

The investigator receives a report in eight parts, in the terminal or as Markdown:

1. the question;
2. the retrieval call (sources, time window, limits, truncation);
3. the events, each tagged with its epistemic level, e.g. `decoded + documented + unknown (8 bytes)`;
4. data gaps, with an explicit list of uninterpretable data;
5. retrieved knowledge with provenance;
6. the exact LLM context;
7. the synthesis, with each cited event marked as found or `✗ NOT IN EVIDENCE`;
8. the validator verdict and any repairs.

*Deviation (D12):* uninterpretable data is listed as `Uninterpreted data: <decoder detail>`, not in the sentence form of the original design ("Event type 0x31 contained payload bytes whose structure is not configured…").

---

## 5. Domain generalisation

### 5.1 What changes per domain

| Fixed in code | Supplied by configuration |
|---|---|
| Event model, retrieval contract, decoding primitives and statuses, epistemic levels, evidence format, synthesis contract, validator | Envelope layout, schema pack Σ, enum maps *M*, knowledge corpus *K* |

Instantiating a new domain takes four steps:
1. assign source ids;
2. write one schema per event type;
3. add enum maps for codes;
4. add domain documents.

No code changes are needed (requirement R7). The test suite checks this by running five domains through the same pipeline and by searching the core code for domain vocabulary.

### 5.2 Five instantiations

| Domain | Sources | Event types (examples) | Cross-source failure used in tests |
|---|---|---|---|
| D1 Drone fleet | drones | POSITION, LIDAR_STATUS, AVOIDANCE, FORMATION_STATE | LiDAR timeout on 298 → avoidance on 474 → 474 leaves formation |
| D2 Microservices | services, DB proxy | REQUEST_METRIC, DB_POOL_STATUS, HTTP_ERROR | DB pool exhausted → order-service latency → payment 504s |
| D3 Industrial line | machines, PLCs | TEMP_STATUS, INTERLOCK, CONVEYOR_STATE | Temperature sensor drift on A → interlock → conveyor B starved |
| D4 Vehicle network (big-endian, CAN-style) | ECUs | WHEEL_SPEED, ECU_FAULT, ABS_STATE, DASH_WARNING | Wheel-speed fault → ABS disabled → warning |
| D5 Warehouse robots | AGVs | BATTERY, NAV_STATE, REPLAN, TASK_STATE | AGV-12 battery critical → AGV-7 replans (with clock skew) |

### 5.3 Grounding the general case in real systems

- **Microservices.** The AWS Kinesis event [R1] is a real instance of the D2 pattern: a root cause in one service propagated through dependencies to many others, while the monitoring path was degraded at the same time. For realistic data, the OpenTelemetry Demo exposes failure-injection feature flags managed by flagd [R19]. Examples include `paymentFailure`, `paymentUnreachable`, `kafkaQueueProblems`, `productCatalogLockContention` and `recommendationCacheFailure`. Each injects a known fault in a known service, which gives ground truth for cross-service evaluation. RCAEval [R15] offers 735 labelled microservice failure cases.
- **Text-log systems.** Loghub [R7] can test whether the decoding and evidence layers degrade gracefully on unstructured logs. That needs a text-payload event type, which is future work.

---

## 6. Case study: multi-drone fleets

### 6.1 Telemetry landscape

**Formal standards.**
- IEEE 1936.1-2021 (Drone Applications Framework) specifies application classes, facility requirements and operation processes. It also covers operation records and reports: data classification, collection and processing, record and analysis, and a data reference format [R20].
- IEEE 1937.3-2024 specifies the content, protocol and transmission of UAV *flight-supervision* data over GNSS short-message links [R21].
- ASTM F3411 specifies message formats and transmission for broadcast and network Remote ID [R22].
- None of these defines an onboard event-log format or crash-recovery semantics for a central log store.

**De facto formats.**
- **MAVLink 2** packets carry a sequence number, system id, component id, a 24-bit message id and a payload whose fields are defined in XML. On the wire, fields are reordered by size, and a CRC is seeded with a per-message `CRC_EXTRA` derived from the definition, so a receiver can detect a definition mismatch [R23].
- **PX4 ULog** is a self-describing log of uORB topics, with format definitions inside the file and a timestamp in every logged format [R24].
- **ArduPilot DataFlash** (.bin) logs are self-describing through FMT records [R25].
- **MCAP** embeds schemas and channels and indexes chunks by time [R6].

### 6.2 Mapping drone telemetry onto FSS

| MAVLink / autopilot concept | FSS concept |
|---|---|
| `sysid` (vehicle) | `source_id` |
| `msgid` (24-bit) | `event_type` (u32) |
| XML message definition | Schema in the D1 schema pack (offsets after wire reordering, little-endian) |
| `CRC_EXTRA` | `schema_version` check on the decoded event |
| Enum definitions (e.g. `MAV_SEVERITY`, mode enums) | Enum map *M* |
| Autopilot documentation (failsafe behaviour, parameter docs) | Knowledge corpus *K* |
| Vehicle timestamp (`time_boot_ms`, ULog µs since boot) | Producer timestamp; clock basis recorded per source |

**Design choice: schemas outside the store.** Autopilot logs carry their own format records. FSS deliberately keeps schemas *outside* the store, in the interpretation layer, so that:

- the store stays protocol-agnostic;
- the same store holds MAVLink, vendor and non-drone events;
- schema errors never threaten durability.

### 6.3 Worked example: Drone 474 leaves formation

**Question:** *"Why did Drone 474 leave formation at about 10:07?"*

**Retrieval:** `retrieve(ALL, 10:06:50, 10:07:10)`. The query is cross-source because the cause may not be on 474.

**Decoded evidence** (producer time):

```
[10:07:01.200] src=474 FORMATION_STATE  state=ACTIVE                          (decoded, documented)
[10:07:02.800] src=298 LIDAR_STATUS     status_code=21 status_name=DEGRADED   (decoded, documented)
[10:07:02.900] src=298 LIDAR_STATUS     status_code=17 status_name=LIDAR_TIMEOUT timeout_count=3
[10:07:03.100] src=474 AVOIDANCE        reason=COLLISION_RISK
[10:07:03.180] src=474 FORMATION_STATE  state=LEFT_FORMATION
[10:07:03.050] src=298 DIAGNOSTIC       PARTIALLY_DECODED, unknown_bytes=8    (unknown region)
```

**Knowledge (documented, with provenance):** what a LiDAR timeout means; how the avoidance planner reacts to collision risk.

**Data quality:**
- 8 bytes of one diagnostic event are uninterpreted;
- clocks of 298 and 474 are not synchronised.

**Expected synthesis:**
- *Likely cause:* a LiDAR degradation and timeout on 298 preceded collision-risk avoidance on 474, which then left formation.
- *Confidence:* medium.
- *Uncertainty:* clock caveat; the ordering across drones is not proof of causation.
- *Data gaps:* the 8 opaque bytes.

The validator checks that each cited event exists and that the caveat and the gap are both present.

### 6.4 Data sources for drones

| Dataset | Content | Multi-agent | Fault labels | Role in FSS |
|---|---|---|---|---|
| PX4 Flight Review public logs [R26] | Large public ULog corpus; CC-BY; bulk download script | No | No | Realistic payloads; decoder coverage; ingest load |
| ALFA [R17] | 47 processed autonomous fixed-wing flights; 23 engine-failure and 24 control-surface-fault scenarios; ground-truth fault time | No | Yes | Real-flight single-agent evaluation |
| RflyMAD [R18] | 114 GB; 11 fault types × 6 flight states; 5,629 cases (SIL, HIL, real) | No | Yes | Fault-type coverage |
| Cyber-physical drone-swarm dataset [R27] | Swarm formations; network telemetry plus positions; CSV | Yes | Cyber-attack | Multi-source retrieval testing |
| U2UData+ [R28] | 15-UAV collaborative flights, 120 h, perception-heavy | Yes | No | Out of scope for the prototype |

**Gap:** we found no public dataset with **labelled cross-agent failure chains**, where a fault on agent A causes behaviour on agent B with ground truth. FSS therefore uses synthetic scenarios (SC1, SC5) and proposes multi-vehicle SITL simulation with fault injection on one vehicle (§6.6).

### 6.5 Regulatory context

India's Drone Rules 2021 were notified on 25 August 2021. They allow authorities to require No-Permission-No-Takeoff hardware/firmware, real-time tracking beacons and geo-fencing in future, and they require operators to report accidents within 48 hours [R29]. Short reporting deadlines are a direct argument for a system that preserves the surrounding evidence and assembles it quickly. In the US, Remote ID (ASTM F3411 as a means of compliance) standardises identification and tracking messages [R22].

### 6.6 Scenario-generation methodology (proposed)

1. Run N simulated vehicles in formation (PX4 SITL, headless).
2. Inject a fault on one vehicle using PX4's failure-injection facility (exact commands to be confirmed in PX4 documentation) and record the injection time as ground truth.
3. Script or observe the neighbour's reaction (avoidance, replan).
4. Add controlled clock offsets per vehicle.
5. Replay the logs through the envelope encoder into FSS.
6. Score attribution against the ground truth.

---

## 7. Evaluation methodology

### 7.1 Research questions

- **RQ1 (Correctness of interpretation):** Does the decoder implement the specification exactly, including edge cases and adversarial inputs?
- **RQ2 (Conformance of the knowledge layer):** Is RAG used only for documented meaning, evidence-driven, provenance-tagged, bounded, and honest about absent documentation?
- **RQ3 (Epistemic honesty of synthesis):** Does the end-to-end system attribute causes correctly while never interpreting unknown data and always qualifying cross-clock causal claims?
- **RQ4 (Generality):** Does one implementation serve five domains by configuration alone?
- **RQ5 (Durability, Java core; future):** Does recovery always yield a valid prefix of acknowledged events under SIGKILL, truncation and bit-flip faults?

### 7.2 Test suite

The full catalogue is in `TEST_CASES.md`. In summary:
- **Spec conformance (SPEC, 24):** traced to the original specification documents.
- **Decoding:** primitives (P, 10), schema validation (S, 11), enums (E, 4), status aggregation (ST, 5).
- **Retrieval contract (R, 10).**
- **Evidence builder and LLM context (V, 10).**
- **RAG conformance (RAG, 14)**, including a gold set of 25 hand-labelled evidence → document queries across all five domains (`tests/rag_gold.yaml`).
- **Progressive investigation (PI, 5).**
- **Validator (Y, 7).**
- **Presentation (UI, 5).**
- **Generalisation and architecture (G 4, ARCH 1).**
- **End-to-end scenarios (SC, 8).**
- **Property-based robustness (B, 5)**, using hypothesis with a fixed seed.
- **Live-LLM evaluation (LLM-EVAL, 7 metrics × 8 scenarios × 3 runs).**

That is 123 non-live IDs plus 7 LLM-EVAL metrics. Unit and scenario tests use a deterministic stub LLM that returns the answer stored with each scenario; they test everything around the model. Live tests sit behind a `live` marker and need an API key.

### 7.3 Metrics

| Metric | Definition |
|---|---|
| Spec conformance | Share of SPEC items implemented *and* passing |
| Attribution accuracy | Fraction of SC1–SC5 runs whose `likely_cause` names the injected cause source and event |
| Citation validity | Share of model-cited events that exist in the evidence, *before* validator repair |
| Unknown preservation | Share of runs with no interpretation of opaque, unknown or undocumented data (before / after validator) |
| Clock humility | Share of cross-source causal claims carrying a caveat (before / after validator) |
| Negative-control correctness | SC6/SC7 runs asserting no cause |
| RAG precision@k | On a gold set of ≥ 20 evidence → document queries |
| Decode throughput | Events/s on the evaluation machine |

### 7.4 Results

All numbers below come from one verification run of the Python layer: 9 October 2026, commit `70285bd`, an AWS EC2 instance (Ubuntu 26.04, 8 vCPU, Python 3.14.4), a fresh virtual environment from pinned dependencies, `MockRetriever` with fixtures, and no Java process. Sources: the run's junit and coverage files, as summarised in `demo/outputs/summary.md` and `TEST_CASES.md`.

**Test catalogue.** "IDs" are catalogue entries; "cases" counts collected test cases, including parametrisations.

| Category | IDs | Cases | Pass | Fail | XFail | Notes |
|---|---|---|---|---|---|---|
| SPEC | 24 | 27 | 27 | 0 | 0 | SPEC-23's envelope part justified as Java-side |
| P / S / E / ST | 30 | 113 | 113 | 0 | 0 | |
| R / V | 20 | 25 | 25 | 0 | 0 | |
| RAG / PI | 19 | 24 | 24 | 0 | 0 | PI tested with the stub LLM only |
| Y / UI | 12 | 30 | 30 | 0 | 0 | |
| G / ARCH | 5 | 7 | 7 | 0 | 0 | |
| SC | 8 | 8 | 8 | 0 | 0 | stub LLM |
| B | 5 | 7 | 7 | 0 | 0 | |
| **Catalogue total** | **123** | **241** | **241** | **0** | **0** | |
| Other tests (K, supporting, live) | n/a | 268 | 260 | 0 | 0 | 8 live cases skipped: no API key |
| **All** | | **509** | **501** | **0** | **0** | |

**Other measurements (same run).**

| Metric | Result |
|---|---|
| RAG precision@3 / recall@3 (25 queries, all domains loaded) | 0.913 / 0.955 |
| RAG precision@5 / recall@5 | 0.890 / 1.000 |
| RAG-01: decoding with the corpus deleted | 109 of 109 decoded events byte-identical (21 documents removed) |
| Decode throughput (B04; 100,000 events over five domains; three runs) | 97,447 / 96,882 / 97,290 events/s |
| Branch coverage: decoder / schema / knowledge / evidence | 95.8% / 87.5% / 92.5% / 100% |
| Total coverage, line / branch | 96.2% / 91.5% |
| Demo `SC1 SC2 SC5 SC6 SC7 Y02` | exit 0, empty stderr; five ACCEPTED, Y02 REJECTED (fabricated citation) |

**Live-LLM evaluation.** Not run: no `FSS_LLM_API_KEY` was available. The metric code is unit-tested on stub runs; every cell is therefore "not run".

| LLM-EVAL metric | Before validator | After validator |
|---|---|---|
| Attribution accuracy (SC1–SC5) | not run | not run |
| Citation validity | not run | n/a (rule 1 rejects invalid citations) |
| Unknown preservation | not run | not run |
| Clock humility | not run | not run |
| Negative controls (SC6–SC7) | not run | not run |
| Stability across 3 runs | not run | not run |
| Validator interventions | not run | not run |

**Reading these results.** The passing catalogue shows that the Python layer implements its specification, including the RAG restrictions and the validator's checks on fabricated citations, omitted gaps and missing clock caveats. It does **not** show how well a real model explains failures: SC1–SC8 pass with a stub that returns stored answers, so RQ3 remains open until LLM-EVAL is run. RQ5 (durability) belongs to the Java core and is outside this run.

---

## 8. Real-world significance

This section merges the verified, cited findings of the companion document `IRL_SIGNIFICANCE.md`. Every source was accessed on 9 October 2026. Where only a secondary source (news, law firm, vendor) or a search excerpt was available, the reference says so; such items are reported, not confirmed.

### 8.1 Failures cross component boundaries, including the logging path

Public postmortems show the two properties FSS is designed around: **(a)** the cause sits in a different component, or organisation, from the visible failure; **(b)** the evidence is lost, incomplete or unreachable when it is needed.

| Incident | Visible failure | Where the cause was | (a) | (b) |
|---|---|---|:-:|:-:|
| AWS us-east-1, Oct 2025 [R32] | EC2 launches, load balancers, Lambda, IAM sign-in | A race condition in DynamoDB's DNS automation | ✓ | |
| AWS S3, Feb 2017 [R33] | S3 and dependants; the status dashboard could not be updated because it depended on S3 | A mistyped capacity-removal command | ✓ | ✓ |
| AWS Kinesis, Nov 2020 [R1] | CloudWatch, Cognito and Lambda errors; metric gaps; the status tool depended on Cognito | A Kinesis front-end thread limit | ✓ | ✓ |
| Meta, Oct 2021 [R34] | DNS unreachable worldwide; internal and out-of-band access down | A backbone maintenance command | ✓ | ✓ |
| Roblox, Oct 2021, 73 h [R35] | Platform down; telemetry depended on the failing Consul cluster | Consul streaming contention plus BoltDB freelist growth | | ✓ |
| Cloudflare, Nov 2025 [R36] | HTTP 5xx from the core proxy; first suspected to be a DDoS | A database permission change doubled a feature file | ✓ | ✓ |
| Google Cloud, Jun 2025 [R37] | 503s across many products, including Cloud Logging and Monitoring; the status page was itself affected | A policy record with blank fields reaching an unguarded code path | ✓ | ✓ |
| CrowdStrike Channel File 291, Jul 2024 [R38, R39, R40] | About 8.5 million Windows devices crashed; Indian airlines moved to manual check-in (secondary) | A content file with 21 fields read by code that supplied 20 (excerpt) | ✓ | |
| NPCI UPI, Apr 2025 [R41] | UPI payments declined nationwide | Reported: bank-side floods of status-check API calls (secondary; NPCI's own RCA not located) | ✓ | |
| Alaska Airlines 1282, Jan 2024 [R42, R43] | Door plug separated in flight | Manufacturing process; the cockpit audio had been **overwritten** | | ✓ |
| Air India AI171, Jun 2025 [R45] | Crash after take-off | Under investigation; the aft recorder could not be downloaded by conventional means | | ✓ |

The pattern maps onto FSS directly. Cross-source retrieval with `source = ALL` addresses (a): scenario SC2 is the microservice analogue of the AWS and NPCI cases. An evidence store that is independent of the system it observes, and recovers after crashes, addresses (b). Reporting gaps as gaps, rather than leaving them silently absent, addresses the Kinesis metric gaps. The CrowdStrike field-count mismatch is the bug class FSS's decoder handles deterministically: it bounds-checks before every read and returns `MALFORMED_PAYLOAD` instead of reading past the end (P05, B02).

### 8.2 Regulation increasingly mandates logs, synchronised clocks and fast reporting

| Jurisdiction | Requirement (paraphrased) | Relevance to FSS |
|---|---|---|
| **India, CERT-In Directions** No. 20(3)/2022, 28 Apr 2022 [R30] | Synchronise ICT clocks to NIC/NPL NTP or a traceable source. Report listed incidents within **6 hours**. Keep logs of all ICT systems for a rolling **180 days within India**. | Retention and fast evidence assembly. Clock synchronisation is mandated precisely because cross-system timestamps need care; FSS treats them as uncertain rather than as ground truth. A 180-day retention policy for the Java store is not built yet. |
| **India, DPDP Rules 2025** [R46] (secondary) | Logging and monitoring of access to personal data; logs kept at least **one year**; most rules take effect 18 months after publication. | A one-year retention floor; FSS never sends raw payload bytes to the LLM, which helps minimisation. |
| **India, drone certification** (CSUAS, S.O. 347(E)) [R47] | The flight module should sign the data it generates with a hardware root of trust, so the origin of its logs can be verified. | FSS computes a content `event_id` but does not verify producer signatures: a gap for drone deployments. |
| **India, Drone Rules 2021** [R29] (secondary) | Accident reporting within 48 hours; future NPNT, tracking beacons, geo-fencing. | Drone evidence preservation and quick reconstruction. |
| **EU AI Act** Art. 12, 19, 26(6), 73 [R31, R48, R49, R50] | High-risk AI systems record events automatically over their lifetime; logs kept at least six months; serious incidents reported within 15 days (2 or 10 days in some cases), without altering the system in a way that compromises later analysis. | FSS's own LLM stage is an AI component: each investigation can be serialised but is **not yet persisted**. Deterministic decoding makes an investigation reproducible (B05). |
| **EU NIS2** Art. 23 [R51] (secondary) | Early warning within 24 hours, notification within 72 hours, final report within one month including the likely root cause. | A stated root cause, with evidence. |
| **US OMB M-21-31** [R52] | Logs kept 12 months active and 18 months cold; protected from tampering by cryptographic methods; millisecond timestamps against a GPS or NIST reference; alerts when logging stops. | FSS's CRC-32C detects accidental corruption, not tampering: hash chaining or signatures are an open gap. |
| **US FAA 25-hour CVR rule** and NTSB retrofit call [R44, R43] | New aircraft must record 25 hours of cockpit audio instead of 2; the NTSB counts at least 14 investigations since 2018 hampered by overwritten recordings. | A rolling buffer that overwrites evidence before investigators reach it is a known failure mode. |

Across India, the EU and the US the same four requirements recur: logs exist and are retained, they are protected from tampering, clocks are synchronised, and incidents are reported quickly with a stated root cause. FSS addresses evidence integrity and explanation. Retention policy, tamper-evidence and persisting its own AI decision records are open.

### 8.3 Data and benchmarks exist, but not for cross-agent binary failures

| Dataset | What it offers (as stated by the source) | Cross-component cause labelled? | Use for FSS |
|---|---|---|---|
| RCAEval [R15] | 735 failure cases on three microservice systems; the RE2 subset has 270 multi-source cases (metrics and logs; traces for two systems); MIT licence | Yes: root-cause service per case | Turn SC2 into a measured accuracy figure |
| OpenTelemetry Demo [R19] | A microservice shop with fault-injection flags (e.g. payment failure, Kafka queue problems) | Yes, by construction | Live runs with a known injected cause; a Java↔Python smoke test |
| RflyMAD [R18] | 5,629 multicopter cases (SIL, HIL, real flights), 11 fault types, binary ULog | No (single vehicle) | Realistic binary payloads for the D1 decoder |
| ALFA [R17] | 47 fixed-wing flights with labelled fault times and types | No (single vehicle) | Status and enum tests on real telemetry |
| Loghub [R7] | Large text-log collections (e.g. HDFS, BGL) with anomaly labels | No | Throughput on real volumes via an adapter |

Our search found **no public multi-UAV dataset with labelled cross-agent failure chains** [R53, R27]. The closest are a single-vehicle multi-fault dataset and a drone-swarm security dataset. No dataset above labels a cause → effect pair across independent producers together with producer clock skew, which is why SC1–SC5 construct both synthetically (§9). RCAEval RE2, paired with the OpenTelemetry Demo, is the best real dataset to adopt next.

### 8.4 Professional relevance

Ten live job postings, retrieved on 9 October 2026 from employers' own boards through the public Greenhouse and Lever APIs, five of them in India (Bengaluru, Bangalore, Gurugram, Hyderabad), were read for their requirements [R54]. By our count of their requirement lines:

- on-call or incident handling appears in 8 of 10;
- distributed systems and explicitly named logs, metrics, traces or telemetry each appear in 7;
- Python appears in 6;
- postmortems or contributing-factor analysis appear in 3;
- AI/ML appears in 2.

FSS exercises these skills directly: cross-source evidence reconstruction, binary protocol decoding, bounded retrieval, and LLM-assisted root-cause analysis whose output is checked against the evidence.

### 8.5 Where existing tools stop

Log platforms already provide crash recovery of their own kinds: Elasticsearch's translog [R55], Loki's write-ahead log [R56], Kafka's CRC-checked log recovery [R57] and MCAP's CRC-protected chunks with a recovery tool [R58]. AI-assisted root-cause analysis is also a product category, e.g. Datadog Watchdog RCA, which separates root cause from impact [R59]. These tools are far more mature than FSS in scale, search and ecosystem. FSS's claim is narrower: the **combination** of a crash-recovery guarantee, deterministic binary decoding with explicit unknowns, a mandatory bounded cross-source retrieval contract, and an LLM explanation that is validated against the evidence. None of the tools above documents all four.

---

## 9. Discussion, limitations and threats to validity

- **Synthetic scenarios.** Cross-agent scenarios are constructed, so attribution accuracy on them is an upper bound on real-world performance. Mitigations: negative controls (SC6/SC7), clock-skew scenarios (SC5), and planned evaluation on ALFA/RflyMAD (single-agent) and OpenTelemetry-Demo/RCAEval (multi-service).
- **The validator checks form, not truth.** It guarantees citations exist and that gaps and caveats are present. It cannot prove the causal story is correct. Correctness is measured separately (LLM-EVAL-1), which has **not yet been run**: every end-to-end result in §7.4 uses a stub LLM. The checks are lexical, so a paraphrased interpretation of unknown data can slip past rule 5.
- **Unsynchronised clocks.** FSS reports temporal order as evidence, not proof. Future work could add per-source offset estimation from causally linked event pairs.
- **RAG quality depends on the corpus.** Poor documentation yields "undocumented" gaps. This is honest but limits explanatory power. Retrieval is exact-term: a document that uses different words from the decoded labels is not found, and the gold set (§7.4) was labelled by the same team that wrote the documents.
- **Durability scope.** The design guarantees process-crash durability. OS-crash and power-loss durability depend on `force()` policy and hardware, and are not testable on cloud VMs.
- **Java core pending.** All Python results use a mock retriever with fixtures. End-to-end durability results await the Java implementation.

## 10. Future work

1. Integrate the Java evidence core, and run SIGKILL / truncation / bit-flip crash campaigns.
2. Multi-vehicle SITL scenario generation with fault injection and ground truth.
3. MAVLink XML → schema-pack generator.
4. A text-payload event type for Loghub-style logs.
5. Tamper-evident (hash-chained or signed) records for forensic use.
6. Clock-offset estimation.
7. A dashboard with a timeline and a data-gaps panel.

## 11. Conclusion

FSS treats failure explanation as an evidence problem first and a language problem second. It preserves evidence through crashes, retrieves it within explicit bounds across all relevant sources, decodes it deterministically, attaches only documented meaning, and lets a language model reason only over what is actually known. The result explains failures and states precisely where the evidence stops. The same implementation applies to drones, services, machines, vehicles and robots by configuration alone.

---

## References

- [R1] AWS. *Summary of the Amazon Kinesis Event in the Northern Virginia (US-EAST-1) Region*, Nov 2020. https://aws.amazon.com/message/11201
- [R2] C. Mohan, D. Haderle, B. Lindsay, H. Pirahesh, P. Schwarz. *ARIES: A Transaction Recovery Method Supporting Fine-Granularity Locking and Partial Rollbacks Using Write-Ahead Logging.* ACM TODS 17(1):94–162, March 1992. doi:10.1145/128765.128770 (checked on Crossref, 2026-10-09)
- [R3] T. S. Pillai et al. *All File Systems Are Not Created Equal: On the Complexity of Crafting Crash-Consistent Applications.* OSDI 2014. https://www.usenix.org/conference/osdi14/technical-sessions/presentation/pillai
- [R4] LevelDB log format. https://github.com/google/leveldb/blob/main/doc/log_format.md
- [R5] J. Kreps, N. Narkhede, J. Rao. *Kafka: a Distributed Messaging System for Log Processing.* NetDB 2011.
- [R6] MCAP specification. https://github.com/foxglove/mcap/tree/main/docs/specification
- [R7] J. Zhu, S. He, P. He, J. Liu, M. R. Lyu. *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics.* arXiv:2008.06448. https://github.com/logpai/loghub
- [R8] D. Clark, C. Meffert, I. Baggili, F. Breitinger. *DROP (DRone Open source Parser) your drone: Forensic analysis of the DJI Phantom III.* Digital Investigation (DFRWS), 2017.
- [R9] E. Mantas, C. Patsakis. *Who Watches the New Watchmen? The Challenges for Drone Digital Forensics Investigations.* Array 14:100135, 2022. arXiv:2105.10917 (checked on DOAJ and DBLP, 2026-10-09)
- [R10] *DroPTC: sentence-level drone flight log forensics using contrastive learning and explainable AI.* https://opus.bibliothek.uni-augsburg.de/opus4/frontdoor/index/index/docId/129376
- [R11] L. Lamport. *Time, Clocks, and the Ordering of Events in a Distributed System.* Communications of the ACM 21(7):558–565, July 1978. doi:10.1145/359545.359563 (checked on Crossref, 2026-10-09)
- [R12] Y. Liu et al. *Interpretable Online Log Analysis Using Large Language Models with Prompt Strategies (LogPrompt).* ICPC 2024. arXiv:2308.07610
- [R13] J. Qi et al. *LogGPT: Exploring ChatGPT for Log-Based Anomaly Detection.* 2023. arXiv:2309.01189
- [R14] Y. Chen et al. *Automatic Root Cause Analysis via Large Language Models for Cloud Incidents (RCACopilot).* EuroSys 2024, Athens. arXiv:2305.15778 (venue checked against the ACM metadata and Microsoft Research page, 2026-10-09)
- [R15] L. Pham, H. Zhang, H. Ha, F. Salim, X. Zhang. *RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data.* arXiv:2412.17015
- [R16] P. Lewis et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020. arXiv:2005.11401 (venue checked, 2026-10-09)
- [R17] A. Keipour, M. Mousaei, S. Scherer. *ALFA: A Dataset for UAV Fault and Anomaly Detection.* IJRR 2021. arXiv:1907.06268; doi:10.1184/R1/12707963
- [R18] X. Le, B. Jin, G. Cui, X. Dai, Q. Quan. *RflyMAD: A Dataset for Multicopter Fault Detection and Health Assessment.* IJRR 2025. arXiv:2311.11340
- [R19] OpenTelemetry Demo: Feature Flags. https://opentelemetry.io/docs/demo/feature-flags/
- [R20] IEEE 1936.1-2021, *Standard for Drone Applications Framework.* https://standards.ieee.org/ieee/1936.1/7455
- [R21] IEEE 1937.3-2024, *Standard for Flight Data Transmission of Civil UAV Based on Short Message Mechanisms.* https://standards.ieee.org/ieee/1937.3/11512/
- [R22] ASTM F3411-22a, *Standard Specification for Remote ID and Tracking.* https://store.astm.org/f3411-22.html
- [R23] MAVLink: Packet Serialization. https://mavlink.io/en/guide/serialization.html
- [R24] PX4: ULog File Format. https://docs.px4.io/main/en/dev_log/ulog_file_format.html
- [R25] ArduPilot: Downloading and Analyzing Data Logs. https://ardupilot.org/plane/docs/common-downloading-and-analyzing-data-logs-in-mission-planner.html
- [R26] PX4: Statistical Flight Log Analysis (Flight Review public logs). https://docs.px4.io/main/en/dev_log/flight_log_analysis_statistical
- [R27] *Cyber-Physical Dataset of Drone Swarms in Coordinated Formations.* IEEE DataPort. https://ieee-dataport.org/documents/cyber-physical-dataset-drone-swarms-coordinated-formations
- [R28] T. Feng et al. *U2UData+: A Scalable Swarm UAVs Autonomous Flight Dataset for Embodied Long-horizon Tasks.* AAAI 2026. arXiv:2509.00055
- [R29] Khaitan & Co. *The Drone Rules 2021: Giving wings to the drone industry in India.* https://khaitanco.com/thought-leaderships/The-Drone-Rules-2021-Giving-wings-to-the-drone-industry-in-India (secondary; cite the Gazette notification in the final version)
- [R30] CERT-In. *Directions under sub-section (6) of section 70B of the Information Technology Act, 2000*, No. 20(3)/2022-CERT-In, 28 April 2022. https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf (primary; accessed 2026-10-09)
- [R31] EU AI Act, Article 12: Record-Keeping. https://artificialintelligenceact.eu/article/12/ (unofficial consolidated text; accessed 2026-10-09)

*References R32–R59 were added from `IRL_SIGNIFICANCE.md` (its source numbers in brackets). All accessed 2026-10-09.*

- [R32] AWS. *Summary of the Amazon DynamoDB Service Disruption in the Northern Virginia (US-EAST-1) Region*, Oct 2025. https://aws.amazon.com/message/101925/ [S1]
- [R33] AWS. *Summary of the Amazon S3 Service Disruption in the Northern Virginia (US-EAST-1) Region*, Feb 2017. https://aws.amazon.com/message/41926/ [S2]
- [R34] Meta Engineering. *More details about the October 4 outage*, Oct 2021. https://engineering.fb.com/2021/10/05/networking-traffic/outage-details/ [S4]
- [R35] Roblox. *Roblox Return to Service 10/28–10/31 2021*, Jan 2022. https://about.roblox.com/newsroom/2022/01/roblox-return-to-service-10-28-10-31-2021 [S5]
- [R36] Cloudflare. *Cloudflare outage on November 18, 2025.* https://blog.cloudflare.com/18-november-2025-outage/ [S6]
- [R37] Google Cloud Service Health. Incident report, 12 Jun 2025. https://status.cloud.google.com/incidents/ow5i3PPK96RduMcb1SsW [S7]
- [R38] CrowdStrike. *Channel File 291 Incident Root Cause Analysis*, 6 Aug 2024. https://www.crowdstrike.com/wp-content/uploads/2024/08/Channel-File-291-Incident-Root-Cause-Analysis-08.06.2024.pdf (search excerpt only) [S8]
- [R39] Microsoft. *Helping our customers through the CrowdStrike outage*, 20 Jul 2024. https://blogs.microsoft.com/blog/2024/07/20/helping-our-customers-through-the-crowdstrike-outage/ [S9]
- [R40] Business Today. CERT-In critical advisory on the Microsoft/CrowdStrike outage, 19 Jul 2024. https://www.businesstoday.in/amp/technology/news/story/microsoft-outage-cert-issues-critical-advisory-govt-takes-cognisance-of-microsoft-outage-437818-2024-07-19 (secondary) [S11]
- [R41] Outlook Money. *UPI outage attributed to surge in API calls from banks, says NPCI*, Apr 2025. https://www.outlookmoney.com/banking/upi-outage-attributed-to-surge-in-api-calls-from-banks-says-npci (secondary) [S12]
- [R42] NTSB. DCA24MA063 Board Meeting Summary, 24 Jun 2025. https://www.ntsb.gov/investigations/Documents/DCA24MA063%20Board%20Meeting%20Summary.pdf (search excerpt only) [S14]
- [R43] NTSB. *NTSB Calls for Retrofit of All CVR-Equipped Airplanes with 25-Hour CVRs*, NR20240213. https://www.ntsb.gov/news/press-releases/Pages/NR20240213.aspx [S15]
- [R44] Federal Register 2026-02110. *25-Hour Cockpit Voice Recorder Requirement, New Aircraft Production*, 2 Feb 2026. https://www.govinfo.gov/content/pkg/FR-2026-02-02/html/2026-02110.htm [S16]
- [R45] AAIB India. *Preliminary Report, B787-8 VT-ANB, Ahmedabad, 12 June 2025.* Read from an unofficial copy: https://indi.ca/content/files/2025/07/Air-India-Crash-Report.pdf; the official copy is on aaib.gov.in (exact URL not located) [S17]
- [R46] SCC Online. *MeitY notified Digital Personal Data Protection Rules, 2025*, 14 Nov 2025. https://www.scconline.com/blog/post/2025/11/14/meity-notified-digital-personal-data-protection-rules-2025/ (secondary; the MeitY PDF returned HTTP 403) [S39]
- [R47] Bureau Veritas India. *UAS – Guidelines for Certification Criteria* (work instructions under S.O. 347(E)), issued 4 Mar 2025. https://cdn1-www.bureauveritas.co.in/sites/g/files/zypfnx556/files/media/document/UAS%20-%20Guidelines%20for%20Certification%20Criteria.pdf [S42]
- [R48] EU AI Act, Article 19. https://artificialintelligenceact.eu/article/19/ [S44]
- [R49] EU AI Act, Article 26. https://artificialintelligenceact.eu/article/26/ [S45]
- [R50] EU AI Act, Article 73. https://artificialintelligenceact.eu/article/73/ [S46]
- [R51] NIS2 Directive (EU) 2022/2555, Article 23 (reproduction of OJ L 333). https://www.springlex.eu/en/packages/nis2/nis2-directive/article-23/ (secondary) [S47]
- [R52] US OMB. *M-21-31: Improving the Federal Government's Investigative and Remediation Capabilities Related to Cybersecurity Incidents*, 27 Aug 2021. https://www.whitehouse.gov/wp-content/uploads/2021/08/M-21-31-Improving-the-Federal-Governments-Investigative-and-Remediation-Capabilities-Related-to-Cybersecurity-Incidents.pdf [S48]
- [R53] IEEE DataPort. *Multi-Fault Dataset of Multirotor UAVs with Single and Double Magnitude Faults.* https://ieee-dataport.org/documents/multi-fault-dataset-multirotor-uavs-single-and-double-magnitude-faults (search excerpt only) [S37]
- [R54] Ten job postings (Razorpay, GitLab, MongoDB, Databricks, Zeta, Datadog ×2, Cloudflare, Nuro, Anduril), live on 2026-10-09; URLs in `IRL_SIGNIFICANCE.md` §7 [S79–S88]
- [R55] Elastic. *Translog settings.* https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog [S63]
- [R56] Grafana Loki. *Write Ahead Log.* https://grafana.com/docs/loki/latest/operations/storage/wal/ [S66]
- [R57] Apache Kafka 3.5 documentation, *Log* (implementation). https://kafka.apache.org/35/implementation/log/ [S75]
- [R58] MCAP specification. https://mcap.dev/spec [S76]
- [R59] Datadog. *Watchdog Root Cause Analysis.* https://docs.datadoghq.com/watchdog/rca/ [S72]

---

## Appendix A: Hard rules (from the Python handoff)

1. Python never reads storage files.
2. The evidence layer owns retrieval.
3. Every retrieval is time-bounded.
4. Only complete EventRecords are returned.
5. The producer timestamp is preserved.
6. No global ordering is promised.
7. Payloads stay binary until decoding.
8. Decoding is deterministic code and configuration.
9. The LLM never decides offsets, types or endianness.
10. Unknown types are not guessed.
11. Unknown regions stay opaque.
12. Unknown bytes are never given to the LLM.
13. Domain documentation supplies meaning.
14. The LLM reasons over decoded evidence only.
15. Cross-agent retrieval goes through `ALL`.
16. Storage internals stay hidden from Python.

## Appendix B: Example schema (D2, microservices)

As shipped in `schema_packs/d2_microservices/db_pool_status.yaml` (real format; see §4.5).

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

## Appendix C: Example schema (D1, drones)

As shipped in `schema_packs/d1_drone_fleet/lidar_status.yaml`. *Correction:* earlier drafts showed event type `0x0101` and a `21: DEGRADED` code; the pack uses type `0x10`, and `DEGRADED` belongs to the DIAGNOSTIC event's enum.

```yaml
schema_set: d1_drone_fleet
enums:
  lidar_status: {0: OK, 17: LIDAR_TIMEOUT, 18: SENSOR_DISCONNECTED, 19: INVALID_SCAN}
event_types:
  0x10:
    name: LIDAR_STATUS
    version: 1
    fields:
      - {name: status_code,   offset: 0, type: u16, size: 2, endian: little, enum: lidar_status, enum_field: status_name}
      - {name: timeout_count, offset: 2, type: u32, size: 4, endian: little}
```
