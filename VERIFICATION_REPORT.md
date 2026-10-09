# FSS Python layer: verification report

Two verification runs on the EC2 instance (`~/fss`), both on 2026-10-09:

- **Run 1** (commit `3c2b8c5`): the FSS_PROJECT §8 catalogue against the handoff. The code as
  received is commit `68f3123`.
- **Run 2** (commit `70285bd`; this revision of the report): the `TEST_CASES.md` catalogue
  (SPEC, RAG, PI, UI, ARCH and LLM-EVAL added), a RAG audit and a 25-query retrieval gold set.

Scope is the Python layer only. The Java evidence core is a teammate's in-progress work; every
test uses `MockRetriever` and fixtures, and run 2's log records no Java process on the host.

## Verdict: complete with deviations (Python layer as now built); incomplete as received

- **As received (`68f3123`), the layer was incomplete.** It implemented the first milestone of
  handoff §23 cleanly (retrieval contract, YAML schemas, deterministic decoder, evidence
  builder), and every catalogue test written against that code passed on its first run. Handoff
  §15-§17 and §21, the FSS_PROJECT §5.8 validator and schema-pack directories were absent; the
  README says so itself ("Not built yet (by design): RAG, LLM calls, the dashboard").
- **As now built (`70285bd`), it is complete with deviations.**
  - SPEC-01 to SPEC-24 all pass; SPEC-23's envelope part is justified as outside Python.
  - RAG-01 to RAG-14 all pass (14/14).
  - All 123 non-live catalogue IDs in `TEST_CASES.md` pass, with 0 xfails.
  - Deviations D1-D13 are recorded below, not silently corrected.
- **The modules that complete the layer were written by the verification runs**, test-first,
  with the owner's approval: `knowledge`, `packs`, `context`, `synthesis`, `llm`, `validator`,
  `investigate` and `presentation`. Run 2 rewrote `knowledge` and `presentation` to meet the new
  catalogue. The team must review this code before the "complete" claim is the team's own (I1).
- **No real LLM has been evaluated.** LLM-EVAL-1 to 7 are "not run": no `FSS_LLM_API_KEY` (I2).

## Contents

1. [Scope and method](#scope-and-method)
2. [Results at a glance](#results-at-a-glance)
3. [Spec conformance: SPEC-01 to SPEC-24](#spec-conformance-spec-01-to-spec-24)
4. [RAG audit and conformance](#rag-audit-and-conformance)
5. [Policy questions](#policy-questions-determined-from-the-code)
6. [Traceability: handoff §2-§23](#traceability-matrix-handoff-2-23)
7. [Traceability: hard rules 1-16](#hard-rules-1-16)
8. [Test counts by category](#test-counts-by-category)
9. [Coverage before and after](#coverage-before-and-after)
10. [Bugs fixed](#bugs-fixed)
11. [Changes made by the verification runs](#changes-made-by-the-verification-runs)
12. [Deviations](#deviations)
13. [Open issues, ranked](#open-issues-ranked-by-severity)
14. [Generalisation (G02 hits)](#generalisation-g02-hits)
15. [Pass criteria](#pass-criteria)

## Scope and method

- **Code:** `~/fss` did not exist on the instance at the start of run 1. The code was in
  `~/minor` (not a git repo), byte-identical to the local copy. It was imported unchanged as
  commit `68f3123`, without build output, caches or the virtualenv. `~/minor` was left untouched
  (its Streamlit app is still bound to 127.0.0.1:8501; no port was opened).
- **Specs:** *python side.pdf* (handoff "HO" §1-§23, authoritative), FSS_PROJECT.md (§5 design,
  §7 hard rules, §8 catalogue), the minor-project PDF ("MP") and, in run 2, `TEST_CASES.md`
  (imported unchanged as `cb7b9b6`). For context: the SRS (FR-10..FR-13, NFR-08..NFR-10) and
  contract/CONTRACT.md.
- **Method (run 1):** read every module and test; run the suite with branch coverage; probe
  each policy question; write the as-received audit (`7960df3`); add catalogue tests against
  the existing code (`d162b26`); add each missing component as failing tests first (`1cd3706`,
  `5a35c4f`), then the implementation.
- **Method (run 2):** audit how RAG was implemented (below); write failing RAG tests and the
  gold set before the ranking existed (`d1f1bbf`), then the implementation (`b26a427`); write
  failing SPEC/UI/PI/ARCH tests (`4357bf8`), then the presentation and output changes
  (`c34283a`); run everything on EC2 in tmux with a script that logs each step; fill
  `TEST_CASES.md` from that run's junit file (`6d18fd7`).
- **Environment (run 2):** EC2, Ubuntu 26.04 LTS, kernel 7.0.0-1006-aws, 8 vCPU, Python 3.14.4.
  A fresh venv from the pinned `requirements.txt`: PyYAML 6.0.3, pytest 9.1.1, pytest-cov
  7.1.0, coverage 7.16.2, hypothesis 6.168.5. Hypothesis uses a fixed-seed profile.

Status key:

- ✅ implemented and tested (team code)
- ✅⁺ implemented and tested by a verification run (new code, needs team review)
- ⚠️ implemented, untested or partly tested
- ❌ missing
- ↔ deviates from the spec (see [Deviations](#deviations))

## Results at a glance

| Item | As received (`68f3123`) | Run 1 (`3c2b8c5`) | Run 2 (`70285bd`) |
|---|---|---|---|
| Tests (cases) | 171 passed | 445 passed, 0 failed, 8 skipped | **509: 501 passed, 0 failed, 0 xfail, 8 skipped** (live LLM, no key) |
| Catalogue IDs passing | none named by ID | 77/77 (FSS_PROJECT §8) | **123/123 non-live** (`TEST_CASES.md`); LLM-EVAL 0/7 run |
| SPEC conformance | n/a | n/a | **24/24 PASS** (SPEC-23 envelope part justified) |
| RAG conformance | n/a (no RAG) | K01-K04 only | **RAG-01 to RAG-14: 14/14 PASS** |
| RAG gold set, 25 queries | n/a | n/a | P@3 **0.913**, R@3 **0.955**; P@5 0.890, R@5 1.000 |
| Branch coverage: decoder / schema / knowledge / evidence | 95.8 / 86.2 / n/a / 100 % | 95.8 / 87.5 / 96.7 / 100 % | **95.8 / 87.5 / 92.5 / 100 %** (required ≥ 85 %) |
| Total coverage (line / branch) | 86.4 / 85.4 % (565 stmts) | 96.2 / 92.0 % (1 222 stmts) | **96.2 / 91.5 %** (1 434 stmts, 458 branches) |
| `run_demo.py SC1 SC2 SC5 SC6 SC7 Y02` | did not exist | exit 0, 435 lines | **exit 0, empty stderr, 514 lines**; ACCEPTED ×5, REJECTED (Y02) |
| B04 decode throughput (100 000 events, five domains) | n/a | 97 318 / 97 123 / 94 943 ev/s | **97 447 / 96 882 / 97 290 ev/s** |
| Generators `--check` (fixtures / scenarios) | 17/17 | 17/17, 16/16 | 17/17, 16/16 |
| `demo/build_outputs.py` (§15 files) | n/a | n/a | exit 0; 7 files in `demo/outputs/` |
| LLM-EVAL-1 to 7 | n/a | n/a | **not run**: no `FSS_LLM_API_KEY` (`llm_eval` exit 2) |

All run-2 numbers come from `/tmp/fss_verify2/log.txt`, `junit.xml` and `coverage.json` on
EC2. `demo/outputs/summary.md` was generated from the same junit and coverage files.

## Spec conformance: SPEC-01 to SPEC-24

Each SPEC item has a dedicated test in `tests/test_catalogue_spec_ui_arch.py` plus the
catalogue tests `TEST_CASES.md` names for it. All passed in run 2 (27 cases: SPEC-03 has 4).

| ID | Requirement (source) | Implementing code | Result |
|---|---|---|---|
| SPEC-01 | Decoder first; LLM does no decoding (HO §6, HR 8-9) | `investigate.py:investigate`, `decoder.py:decode` | PASS |
| SPEC-02 | Schema fields: name, offset, type, size, endian (HO §7) | `schema.py:parse_schema` | PASS ↔ D2 |
| SPEC-03 | Primitives, explicit signedness and endianness (HO §8) | `schema.py:PRIMITIVES` | PASS ↔ D3 |
| SPEC-04 | Enum maps; unmapped → `UNKNOWN` (HO §9) | `decoder.py:_enum_label` | PASS |
| SPEC-05 | Unknown type kept, not sent to the LLM (HO §10) | `decoder.py:26-31`, `context.py` | PASS |
| SPEC-06 | Known prefix + opaque tail → `PARTIALLY_DECODED` (HO §11) | `decoder.py:58-59` | PASS |
| SPEC-07 | Bounds before every read → `MALFORMED_PAYLOAD` + reason (HO §12) | `decoder.py:37-40` | PASS ↔ D4 |
| SPEC-08 | `DecodedEvent` fields (HO §13) | `model.py:DecodedEvent` | PASS ↔ D1 |
| SPEC-09 | Decoded / documented / unknown kept distinct (HO §14, MP §8) | `context.py` event lines (`decoded`, `documented`), data-quality section | PASS |
| SPEC-10 | Knowledge separate from schemas (HO §15, MP §8) | `knowledge.py`, `packs.py` (`docs/`) | PASS |
| SPEC-11 | Six document kinds (HO §15) | `knowledge.py:KINDS` | PASS |
| SPEC-12 | RAG retrieved together with the evidence (MP §8) | `knowledge.py:KnowledgeBase.lookup(evidence)` | PASS |
| SPEC-13 | Undocumented value keeps its uncertainty (MP §8) | `knowledge.py` (`undocumented`), `context.py` `[UNDOCUMENTED_VALUE]` | PASS |
| SPEC-14 | LLM only synthesises (HO §16, HR 14) | `synthesis.py`, `validator.py` rule 5 | PASS |
| SPEC-15 | Extra context only via bounded retrieval (HO §17, MP §9) | `investigate.py:to_retrieval_request` | PASS |
| SPEC-16 | Cross-agent `ALL`, no hard-coded relations (HO §18) | `model.py:ALL`, G02 | PASS |
| SPEC-17 | No clock sync assumed (HO §19) | `evidence.py` clock caveat, validator rule 4 | PASS |
| SPEC-18 | Context = query + events + knowledge + data quality (HO §20) | `context.py:build_context` | PASS ↔ D5 |
| SPEC-19 | Output contract (HO §21) | `synthesis.py:FailureSynthesis` | PASS ↔ D9 |
| SPEC-20 | Investigator sees events, context, interpretation, synthesis, unknowns (FR-13, MP §10) | `presentation.py` (eight parts) | PASS ↔ D12 |
| SPEC-21 | AI never has to infer raw fields (NFR-09) | `context.py`, V01 | PASS |
| SPEC-22 | Layer separation (NFR-10) | import graph, ARCH-01 | PASS |
| SPEC-23 | Per-deployment envelopes and schemas (NFR-08, MP §4) | schema packs, G01-G04 | PASS for schemas; **envelope part justified**: the envelope is fixed by contract v0 at the Java ingest and Python only sees `EventRecord`s |
| SPEC-24 | Python runs without Java (HO §23) | `retriever.py:MockRetriever` | PASS (log: `java processes: none`) |

## RAG audit and conformance

**How RAG was implemented at the start of run 2 (`17bd55b`, from reading `knowledge.py`).**

- Whole-document retrieval: a document matched if one of its front-matter `keys` equalled an
  event name or documented enum label in the evidence. No embeddings, no vector store, no
  ranking.
- Present: deterministic exact-term matching; undocumented terms reported; enum maps resolved in
  the decoder before any document is consulted; provenance by document id.
- Absent, compared with `TEST_CASES.md` §7: document kinds (RAG-03); chunks and chunk ids
  (RAG-09); the question taking part in the query (RAG-05); a top-k budget with truncation
  reported (RAG-11); an explicit "no domain documentation" note (RAG-12); document-defined code
  meanings (MP §8 `planner_state 4`), undocumented *values* (RAG-07), and conflicts between
  documents or with the enum map (RAG-02, RAG-08); a gold set (RAG-04).

**What run 2 built** (`d1f1bbf` failing tests and gold set → `b26a427` implementation):

- Documents declare one of six kinds and split into paragraph chunks, each with document id,
  chunk id `doc#n`, kind and domain (the pack directory).
- Candidates come only from evidence: event names and documented labels (`keys`), or code
  values a document defines (`codes:`). Question words only re-rank: label match 10, event
  match 5, code match 5, +1 per question word (`knowledge.py:41`).
- At most `top_k` = 8 chunks (`knowledge.py:40`); a cut is reported as `[KNOWLEDGE_TRUNCATED]`.
- Document-defined code meanings are shown as *documented* with their document id. A value of a
  covered field with no definition is `[UNDOCUMENTED_VALUE]`. Disagreements (document vs
  document, document vs enum map) are `[KNOWLEDGE_CONFLICT]` with every claim; nothing is
  resolved silently.
- Nothing relevant → `[NO_DOMAIN_DOCUMENTATION]`, and the pipeline continues.
- Corpus: `kind` added to all 17 documents; four new documents (error-code table,
  architecture, protocol, state description), 21 in total.

| ID | Result | Evidence (run 2) |
|---|---|---|
| RAG-01 | PASS | 21 documents deleted; 109/109 decoded events across SC1-SC8 byte-identical (`demo/outputs/RAG_conformance.md`) |
| RAG-02 | PASS | Enum map resolves 17 → `LIDAR_TIMEOUT`; the document only explains; a disagreeing document is surfaced |
| RAG-03 | PASS | Six kinds ingest; every chunk carries doc id, chunk id, kind, domain |
| RAG-04 | PASS | Gold set, 25 queries, all domains loaded: P@3 0.913, R@3 0.955; P@5 0.890, R@5 1.000 (threshold in the test: P@3 ≥ 0.8) |
| RAG-05 | PASS | Query records evidence terms and question terms; the question re-ranks but never adds candidates |
| RAG-06 | PASS | Same evidence twice → identical chunks, order and context |
| RAG-07 | PASS | `planner_state = 9` with only code 4 documented → `[UNDOCUMENTED_VALUE]`; stub synthesis does not explain it |
| RAG-08 | PASS | Two documents disagree on code 4 → both shown, `[KNOWLEDGE_CONFLICT]` |
| RAG-09 | PASS | Every snippet: `<document id chunk kind domain tag="documented">` |
| RAG-10 | PASS | SC2 with every domain loaded retrieves only `d2_microservices` chunks (isolation by relevance, D11) |
| RAG-11 | PASS | 200 relevant chunks → 8 kept, `[KNOWLEDGE_TRUNCATED] 192 …` (chunk count, not tokens: D10) |
| RAG-12 | PASS | No match → `[NO_DOMAIN_DOCUMENTATION]`; investigation still completes |
| RAG-13 | PASS | Injection text appears only quoted inside `<document>`; no section header can be forged |
| RAG-14 | PASS | A new document is retrieved after reloading the pack, with no code change |

Required by the pass criteria: RAG-01, 02, 05, 07 and 09 all pass.

## Policy questions (determined from the code)

| Question | Answer | Where | Test |
|---|---|---|---|
| Timestamp unit | **u64 nanoseconds** (`timestamp_ns`), the producer's value copied verbatim. The handoff examples use ms; the contract fixes ns. Fixtures and scenarios use UTC epoch ns. | `model.py:40`, `decoder.py:24` | `test_rule_05`, V06, SC5 |
| Retrieval interval | **Half-open `[t_start_ns, t_end_ns)`**, unsigned. Window ≤ 1 h, `1 ≤ max_events ≤ 10 000`. Invalid requests are rejected, never clamped. This also applies to LLM context requests. | `model.py:124-138` | R01-R03, PI-02, PI-03 |
| Fields decoded before a malformed field | **Discarded.** All-or-nothing: `MALFORMED_PAYLOAD` has `fields = {}` and `unknown_bytes = payload_len`. | `decoder.py:37-40,69-73` | P05, ST05, B02 |
| NaN / ±inf in JSON | Kept as floats, one warning per field, and serialised as the strings `"NaN"`, `"Infinity"`, `"-Infinity"`, so `allow_nan=False` succeeds. `-0.0` is kept. | `model.py:64-68`, `decoder.py:51-52` | P02 (24 cases) |
| Non-canonical boolean (byte ∉ {0,1}) | The **whole event becomes `MALFORMED_PAYLOAD`**, with reason `field '<f>' is bool but byte <a> has value <v> (expected 0 or 1)`. There is no warning-and-coerce path (D8). | `decoder.py:42-46` | P03 |
| Can raw payload bytes reach the LLM context? | **No path for opaque regions or unknown-type payloads.** `DecodedEvent` carries no payload. The evidence and the rendered context carry decoded values, labels, counts and reasons only. **One narrow path:** the non-canonical-bool reason quotes that single byte's value. The byte belongs to a schema-declared field, not an opaque region. | `decoder.py:44`, `context.py` | V01 (11 regions in hex/base64/int-list forms), `test_rule_12`, `test_report_never_shows_payload_bytes` |

## Traceability matrix: handoff §2-§23

| § | Requirement | Implementing code | Tests | As received | After |
|---|---|---|---|---|---|
| 2 | `retrieve(source\|all, start, end, event_type?)`, always bounded | `model.py:RetrievalRequest`, `retriever.py:MockRetriever.retrieve` | R01-R08, `test_retriever.py`, `test_rule_03` | ✅ | ✅ |
| 3 | Java internals | none needed in Python | `test_rule_16`, R10 | n/a | n/a |
| 4 | `EventRecord(source_id, timestamp, event_type, payload_bytes)` | `model.py:EventRecord` | `test_rule_04`, `test_wire_vectors.py` | ✅ ↔ D1 | ✅ ↔ D1 |
| 5 | No global order; unknown types and undecodable payloads possible | `evidence.py:build_evidence` | R09, V07, `test_rule_06` | ✅ | ✅ |
| 6 | Deterministic decoder; the LLM never decodes | `decoder.py:decode` | P01-P10, B01-B05, `test_fuzz.py` | ✅ | ✅ |
| 7 | Schema: name, offset, type, size, endian | `schema.py:parse_schema`; packs: `packs.py:load_pack` | S01-S11, `test_schema.py` | ✅ ↔ D2 | ✅ ↔ D2; ✅⁺ pack directories |
| 8 | Primitive types with explicit size, sign and endianness | `schema.py:PRIMITIVES` | P01 (48), P02 (24), G03 | ✅ ↔ D3 | ✅ ↔ D3 |
| 9 | Enums; unmapped → `UNKNOWN` | `schema.py:_parse_enums`, `decoder.py:_enum_label` | E01-E04 | ✅ | ✅ |
| 10 | Unknown type → `UNKNOWN_EVENT_TYPE`, not guessed, not for the LLM | `decoder.py:26-31`; `context.py:_events` | ST03, V02, SC3, SC7, Y04 | ✅ | ✅ (and ✅⁺ for the LLM path) |
| 11 | Opaque bytes → `PARTIALLY_DECODED`, `unknown_bytes` | `decoder.py:58-59` | P08, P09, ST02, V03 | ✅ | ✅ |
| 12 | Bounds before every read → `MALFORMED_PAYLOAD` + reason | `decoder.py:37-40` | P05, P07, ST04, ST05, V04, B02 | ✅ ↔ D4 | ✅ ↔ D4 |
| 13 | `DecodedEvent` | `model.py:DecodedEvent` | `test_fixtures.py`, SC goldens | ✅ ↔ D1 | ✅ ↔ D1 |
| 14 | Decoded / documented / unknown | `interpreted_fields`, `data_gaps`, the context's `"documented"` | K01, `test_rule_13`, V03 | ✅ | ✅ |
| 15 | Domain knowledge / RAG | `knowledge.py:KnowledgeBase.lookup`, `packs.py` (`docs/*.md`) | RAG-01 to RAG-14, K01-K04, V08, `test_catalogue_packs.py` | ❌ | ✅⁺ ↔ D10, D11 |
| 16 | LLM reasons and synthesises | `synthesis.py`, `llm.py`, `investigate.py:investigate` | Y01-Y07, SC1-SC8; LLM-EVAL live **not run** | ❌ | ✅⁺ (stub); live ⚠️ |
| 17 | The LLM may request more context, always bounded | `investigate.py:to_retrieval_request` | PI-01 to PI-05 | ❌ | ✅⁺ (stub only; see I5) |
| 18 | Cross-agent retrieval; no hard-coded relationships | `ALL` sentinel; no domain words in core | R05, SC2, G02 | ✅ | ✅ |
| 19 | No clock sync; state uncertainty | `evidence.py:_clock_caveat`; validator rule 4 | V05, Y05, SC5 | ✅ evidence / ❌ synthesis | ✅ / ✅⁺ |
| 20 | Context = query + decoded events + domain knowledge + data-quality warnings | `context.py:build_context` (four sections) | V01-V10 (V09: exactly four parts), SPEC-18 | ⚠️ 3 of 4 parts, no rendering | ✅⁺ ↔ D5 |
| 21 | `FailureSynthesis` contract | `synthesis.py:FailureSynthesis`, `parse_output` | Y01, Y06, SPEC-19 | ❌ | ✅⁺ ↔ D9 |
| 22 | Hard rules | see below | `test_hard_rules.py` + catalogue | see below | see below |
| 23 | Minimal pipeline, mock → … → synthesis | `investigate.py`; `scenarios.run_scenario` | SC1-SC8, G01 | ⚠️ first milestone only | ✅⁺; real Java interface ❌ (milestone I1) |

FSS_PROJECT.md §5 items not in the handoff:

| §5 item | As received | After |
|---|---|---|
| 5.2 Packs: directory of YAML files, duplicates across files, discovery | ❌ | ✅⁺ S06, S10, G04 |
| 5.2 Load-time validation (all eight listed checks + safe loader) | ✅ | ✅ S01-S11 (S11 includes 2⁴⁰ and 2⁶⁴) |
| 5.6 Byte-identical context | ✅ (dict) | ✅⁺ rendered text, V07 |
| 5.8 Output validator, six rules | ❌ | ✅⁺ Y01-Y07, V08, SC5, SC7, Y02 report |
| 5.9 Presentation | ⚠️ drone-specific Streamlit only | ✅⁺ `presentation.py` (eight parts, terminal + markdown), `demo/run_demo.py`, `demo/build_outputs.py`; UI-01 to UI-05 |

## Hard rules 1-16

Each rule has at least one passing test. The pass criteria require rules 1, 3, 5, 8-14 and 16.

| # | Rule | Passing tests |
|---|---|---|
| 1 | Python never reads Java storage | `test_rule_01`, R10, `test_rejects_storage_framed_files` |
| 2 | Java owns retrieval | `test_rule_02` |
| 3 | Every retrieval is time-bounded | `test_rule_03` ×4, R01, R02, PI-02, PI-03 (LLM requests: rejected, not clamped) |
| 4 | Complete EventRecords | `test_rule_04` |
| 5 | Producer timestamp preserved | `test_rule_05`, V06, SC5 |
| 6 | No global ordering | `test_rule_06`, R09, V07 |
| 7 | Payload binary until decoding | `test_rule_07` |
| 8 | Deterministic decoding | `test_rule_08`, P01-P10, B05 |
| 9 | LLM never decides offsets, types, endianness | `test_rule_09`, V01 (no layout terms in the context) |
| 10 | Unknown types not guessed | `test_rule_10`, ST03, SC3, SC7 |
| 11 | Unknown regions opaque | `test_rule_11`, P08, P09, ST02 |
| 12 | Unknown bytes not given to the LLM | `test_rule_12`, V01, V02 |
| 13 | Documentation supplies meaning | `test_rule_13`, E01-E04, K01-K04, RAG-01, RAG-02, RAG-07 |
| 14 | LLM reasons over decoded evidence only | `test_rule_14`, Y04 (×5), V08, SC7 |
| 15 | Cross-source retrieval via ALL | `test_rule_15`, R05, SC2 |
| 16 | Storage internals hidden | `test_rule_16`, R10 |

## Test counts by category

Run 2, from `--junitxml` on EC2 at `70285bd`, grouped by the test-name prefix
(`demo/outputs/summary.md`). "Cases" counts collected test cases, including parametrisations.
Run 1's counts (453 cases) are in git history (`2235b7d`).

| Category | Catalogue IDs (`TEST_CASES.md`) | Cases | Pass | Fail | xfail | Skipped |
|---|---:|---:|---:|---:|---:|---:|
| SPEC spec conformance | 24 | 27 | 27 | 0 | 0 | 0 |
| P primitives | 10 | 82 | 82 | 0 | 0 | 0 |
| S schema | 11 | 19 | 19 | 0 | 0 | 0 |
| E enums | 4 | 7 | 7 | 0 | 0 | 0 |
| ST status | 5 | 5 | 5 | 0 | 0 | 0 |
| R retrieval | 10 | 14 | 14 | 0 | 0 | 0 |
| V evidence/context | 10 | 11 | 11 | 0 | 0 | 0 |
| RAG | 14 | 18 | 18 | 0 | 0 | 0 |
| PI progressive investigation | 5 | 6 | 6 | 0 | 0 | 0 |
| Y validator | 7 | 25 | 25 | 0 | 0 | 0 |
| UI presentation | 5 | 5 | 5 | 0 | 0 | 0 |
| G generalisation | 4 | 6 | 6 | 0 | 0 | 0 |
| ARCH | 1 | 1 | 1 | 0 | 0 | 0 |
| SC scenarios | 8 | 8 | 8 | 0 | 0 | 0 |
| B robustness | 5 | 7 | 7 | 0 | 0 | 0 |
| K knowledge (FSS_PROJECT §8, kept) | n/a | 4 | 4 | 0 | 0 | 0 |
| Supporting (pre-existing, packs lint, scenario oracle, CLI, LLM client, presentation, live) | n/a | 264 | 256 | 0 | 0 | 8 (live LLM, no key) |
| **All** | **123 non-live + 7 LLM-EVAL** | **509** | **501** | **0** | **0** | **8** |

LLM-EVAL-1 to 7 are "not run" in `TEST_CASES.md`. Their metric code
(`scenarios/llm_eval.py`) is unit-tested on stub runs; the live runner exited 2 without a key.

Where the catalogue asks for a "documented policy", the tests assert what the code does:

| Test | Policy asserted |
|---|---|
| P02 | Non-finite floats become strings, with a warning |
| P03 | A non-canonical bool makes the event MALFORMED |
| P10 | Runs at the largest legal payload, 65 504 bytes. A 65 536-byte payload is rejected by `EventRecord` (CONTRACT §10.1). |
| R03 | Half-open interval |
| S10 | An empty pack *directory* loads; an empty schema *file* is rejected (D7) |
| S02/S03 | Use the code's type names `u32`/`u24` as well as `uint24` (D3) |

## Coverage before and after

`pytest --cov=fss_py --cov-branch` on EC2. Line / branch, in percent. ⁺ marks verification-run
modules.

| Module | As received | Run 1 (`3c2b8c5`) | Run 2 (`70285bd`) |
|---|---|---|---|
| decoder.py | 98.3 / **95.8** | 98.3 / **95.8** | 98.3 / **95.8** |
| schema.py | 92.4 / **86.2** | 93.0 / **87.5** | 93.0 / **87.5** |
| knowledge.py ⁺ | n/a | 97.5 / **96.7** | 96.3 / **92.5** |
| evidence.py | 100 / **100** | 100 / **100** | 100 / **100** |
| model.py | 93.3 / 78.6 | 94.4 / 82.1 | 94.4 / 82.1 |
| retriever.py | 100 / 83.3 | 100 / 83.3 | 100 / 83.3 |
| wire.py | 100 / 100 | 100 / 100 | 100 / 100 |
| cli.py | 0 / 0 | 96.8 / 100 | 96.8 / 100 |
| packs.py ⁺ | n/a | 97.3 / 90.0 | 97.3 / 90.0 |
| context.py ⁺ | n/a | 98.5 / 90.9 | 98.8 / 93.3 |
| synthesis.py ⁺ | n/a | 99.1 / 97.6 | 99.1 / 97.6 |
| validator.py ⁺ | n/a | 98.0 / 92.1 | 98.0 / 92.1 |
| investigate.py ⁺ | n/a | 94.9 / 93.8 | 94.9 / 93.8 |
| llm.py ⁺ | n/a | 89.7 / 87.5 | 89.7 / 87.5 (live call path tested against a fake API only) |
| presentation.py ⁺ | n/a | 94.0 / 81.8 | 95.0 / 80.6 |
| **Total** | **86.4 / 85.4** | **96.2 / 92.0** | **96.2 / 91.5** (1 434 statements, 458 branches) |

The pass criterion (≥ 85 % branch on decoder, schema, knowledge, evidence) is met. Knowledge
fell from 96.7 to 92.5 % because the module grew from whole-document lookup to chunks, codes
and conflicts (80 branches; 6 partial). `__main__.py` (3 lines) stays at 0 %: it only calls
`cli.main`, which is covered.

## Bugs fixed

**None in team code**, in either run. No catalogue test failed because of a defect in the
received code, so no fix was needed and no test is marked xfail.

Failures seen during the runs had three causes, none in team code:

- **Tests written before their implementation** (by design): `1cd3706`, `5a35c4f` (run 1);
  `d1f1bbf`, `4357bf8` (run 2).
- **Intended format changes in run 2.** The richer context (decoded/documented groups, chunk
  provenance) changed K04's expected document list, V03's key and the scenario goldens. They
  were updated deliberately (`b26a427`, `7ed31d6`); all eight verdicts were unchanged.
- **Mistakes in verification-run code, caught before commit:** an SC3 ordering and a V08
  count in my own tests (run 1); in run 2, `scenarios/llm_eval.py` passed the evidence dict
  instead of its event list to `find_event`, which the LLM-EVAL metric unit test caught.

The one change to team logic was the G02 clean-up (`deb9ebe`), a pure refactor recorded under
[Generalisation](#generalisation-g02-hits).

## Changes made by the verification runs

All changes are additive unless noted.

| Commit | Change |
|---|---|
| `68f3123` | Import as received |
| `b19b64c` | Pinned `requirements.txt` / `requirements-app.txt`; `.gitignore`; `live` marker |
| `7960df3` | As-received audit (this report's first version) |
| `d162b26` | Catalogue P, S, E, ST, R, B tests (all passed against team code) |
| `1cd3706` → `b14d657` | Failing pack/knowledge tests → `packs.py`, `knowledge.py`. Team code touched in two places: `SchemaRegistry.__iter__` (additive), and the static file-access allowlists in `test_rule_01` and R10 now include the new configuration loader. |
| `8d76aba` | Schema packs D1-D5 (+ docs) |
| `acbcaf2` | SC1-SC8 generators (struct-packed oracle) and K01-K04 |
| `5a35c4f` → `bacd27d` | Failing V/Y tests → `context.py`, `synthesis.py`, `validator.py`, `llm.py`, `investigate.py` |
| `31bab4a` | SC1-SC8 end-to-end tests + goldens (`tests/golden/`); G01-G04 (G02 failing) |
| `54233ee` → `deb9ebe` | CLI characterisation tests → G02 refactor (team code: `cli.py`, `schema.py` docstring) |
| `a85cadf` | B01-B05 over all packs; Y08 live test |
| `d01ad7b` | `presentation.py`, `demo/run_demo.py` |
| `3c2b8c5` | Offline tests for the live LLM client and context-request parsing (end of run 1) |
| `2235b7d` | Run-1 documents |
| `17bd55b` | IRL_SIGNIFICANCE.md (research, cited) |
| `cb7b9b6` | Run 2: import `TEST_CASES.md` and `FSS_RESEARCH_PAPER.md` unchanged |
| `d1f1bbf` → `b26a427` | Failing RAG-01..14 tests + 25-query gold set → knowledge rewrite (chunks, kinds, query, budget, code meanings, conflicts); four new documents |
| `7ed31d6` | Scenario goldens regenerated for the new context format (verdicts unchanged) |
| `4357bf8` → `c34283a` | Failing SPEC/V10/PI/UI/ARCH tests and ID renames → eight-part presentation, `demo/build_outputs.py`, `scenarios/llm_eval.py`, `scenarios/rag_gold.py` |
| `70285bd` | Live test renamed to LLM-EVAL (the commit run 2 ran on) |
| `6d18fd7` | `TEST_CASES.md` filled and `demo/outputs/` from the run |

## Deviations

Code versus spec. Where marked "decision", the code was left as is and the decision belongs to
the team or the mentor.

| ID | Where | Spec | What the code does | Impact | Proposed fix |
|---|---|---|---|---|---|
| D1 | `model.py:40,71-102` | handoff §4/§13 `timestamp`, `event_type: int\|str` | `timestamp_ns` (u64 ns); numeric `event_type` plus `event_name`; extra keys | Cosmetic | Done: FSS_PROJECT §5.3 now shows the real shape |
| D2 | `schema.py:261-272` | FSS_PROJECT §5.2: per-type file with top-level `event_type`/`name`/`fields`, inline enums | `schema_set` / named `enums` / `event_types: {id: …}`. The old §5.2 example is rejected (`unknown key(s) ['event_type', 'fields', 'name']`). | The documented example didn't load | Done: §5.2 updated; packs use one file per event type in the real format |
| D3 | `schema.py:21-26` | `uint8…uint64, int8…, float32/64, boolean` | `u8…u64, i8…i64, f32, f64, bool`; `uint32` is an unknown type | Catalogue wording only | Decision: keep (§5.2 updated) or add aliases (a schema-format change) |
| D4 | `decoder.py:38-40` | "required: bytes 8–11, available: bytes 8–9" | `field 'b' needs bytes 8..11 but payload has 10 bytes` | None | None |
| D5 | `evidence.py:21-27` | §5.6 "events listed by producer timestamp"; handoff §20 shows one timeline | Grouped by source, producer time within a source, no cross-source timeline | Deliberate (OPEN_QUESTIONS #6) | Decision (mentor) |
| D6 | `evidence.py:52` | §5.6: unknown/malformed events appear **only** in data gaps | `build_evidence()["events"]` also lists them, with `fields = {}`. The new LLM context (`context.py`) lists them only under data quality (V02). The Streamlit "Explain with Claude" path still sends the raw evidence dict. | Low | Done for the pipeline. Decision: switch Streamlit to `investigate()` (I7) |
| D7 | `schema.py:269-271` | S10 "empty schema pack loads" | An empty schema *file* is rejected; an empty pack *directory* loads | Low | None needed |
| D8 | `decoder.py:42-46` | P03 "warning on non-canonical" | Non-canonical bool → whole event `MALFORMED_PAYLOAD` | Low: safer, but one bad flag hides the whole event | Decision (mentor) |
| D9 | `synthesis.py` (new) | handoff §21 `likely_cause` is a string | `likely_cause` may be `null` ("no cause asserted", SC6/SC7). A contributing event may name an unconfigured type by its hex id (so rule 5 can flag it). | Contract extension | Decision: accept, or use a sentinel string |
| D10 | `knowledge.py:40` (`DEFAULT_TOP_K`) | TEST_CASES RAG-11 / paper §4.7 "top-k and token budgets" | The budget is a chunk count (`top_k` = 8). There is no token budget. | A few very long chunks could still make a large context | Add a token (or character) cap alongside `top_k`, reported the same way |
| D11 | `knowledge.py:KnowledgeBase.lookup` | paper §4.7 "domain tags keep drone manuals out of a microservice investigation" | Isolation is by relevance: candidates must match evidence terms. `domain` is recorded as provenance but never used as a filter. RAG-10 passes on that basis. | A generic label shared by two domains could pull the other domain's chunk (I6) | Optional filter on the evidence's pack/domain |
| D12 | `presentation.py:85` | MP §10 example "Event type 0x31 contained payload bytes whose structure is not configured…" | `Uninterpreted data: <decoder detail>`, e.g. "8 payload bytes … not described by the schema" | Wording only | None, or adopt the MP sentence as a template |
| D13 | n/a (Java side) | SPEC-23 / NFR-08 per-deployment envelopes | Python consumes `EventRecord`s; the envelope layout is fixed by contract v0 at the Java ingest | None for Python | Justified: out of Python scope |

`FSS_RESEARCH_PAPER.md` §4 disagreed with the code in four places. Each was corrected in the
paper with a note pointing here: §4.5 type names (D3); §4.7 budget and isolation (D10, D11);
§4.8 event-line format and grouping (D5); Appendices B and C, which used the pre-D2 schema
format and enum values the packs do not have.

## Open issues, ranked by severity

| # | Severity | Issue | Evidence | Proposed action |
|---|---|---|---|---|
| I1 | **High** | The modules that make the layer complete (§15-§17, §20 rendering, §21, §5.8, presentation) were written by the verification runs, not the team. Run 2 rewrote `knowledge` and `presentation`. They are tested, but the team has not reviewed or owned them. | Matrix ✅⁺ rows | Team code review of `knowledge`, `packs`, `context`, `synthesis`, `validator`, `investigate`, `llm`, `presentation` |
| I2 | **High** | No real LLM was ever exercised. `FSS_LLM_API_KEY` was not available, so LLM-EVAL-1 to 7 are "not run", the 8 live cases skipped, and `AnthropicLLM` was tested only against a fake API. Whether a real model follows the contract, caveats and gap reporting is unknown. | 8 skipped; `llm_eval` exit 2 | `FSS_LLM_API_KEY=… python -m scenarios.llm_eval --runs 3`, then `demo/build_outputs.py --llm-eval demo/outputs/live/llm_eval.md` |
| I3 | Medium | The validator is lexical. Rule 4 looks for "clock" in `uncertainty`. Rule 5 looks for event ids, unconfigured hex type ids, phrases like "opaque bytes" and hex dumps. Rule 3 looks for each gap's event_id (or "truncat"). Paraphrases can slip through, and a plausible but wrong story that cites real events cannot be detected. | `validator.py` | Keep the rules as a floor; measure with LLM-EVAL and review live outputs by hand |
| I4 | Medium | YAML 1.1 integer forms are accepted silently: `offset: 010` reads as **8** (octal), `1:20` as **80** (base 60), `0b11` as 3. Booleans and duplicate keys are guarded; these are not. | Run-1 probe | Restrict the int resolver in `schema._StrictLoader` to decimal and `0x` (a format change: needs team sign-off) |
| I5 | Medium | Progressive retrieval (§17, PI-01 to PI-05) works only with the stub. The live client constrains output to the `FailureSynthesis` schema, so it cannot send a `context_request`; live runs use `max_context_requests=0`. | `llm.py` docstring | Add a second schema (`anyOf` synthesis / request) and a live test |
| I6 | Medium | No token budget for knowledge (D10); isolation by relevance only (D11). | RAG-11, RAG-10 | See D10, D11 |
| I7 | Low | `streamlit_app.py` predates this work and is not on the pipeline: drone-specific (a hard-coded `RULES` table and system prompt), sends the evidence dict, free-text answer, not validated. | `streamlit_app.py:32-52,119-135` | Rebuild it on `investigate()` + `presentation` |
| I8 | Low | CLI: an invalid `--source` (e.g. `0474`) or unknown `--event-type` name ends in a traceback, not a usage error. | `cli.py:65-71` | Catch `ValueError`/`KeyError` → `p.error(...)` |
| I9 | Low | Exact-term retrieval: a document that uses different words from the labels is not found (no synonyms, no embeddings). The gold set's misses at k = 3 are listed in `demo/outputs/RAG_conformance.md`. | RAG-04 | Write `keys`/`codes` for every label a document explains; consider an optional embedding re-ranker that cannot add candidates |
| I10 | Low | The non-canonical-bool reason quotes that byte's value into the context (one byte of a declared field). | `decoder.py:44` | Accept, or drop the value from the reason |
| I11 | Info | u64 timestamps exceed 2⁵³: any JavaScript consumer (the dashboard) must treat them as strings (OPEN_QUESTIONS #8). | | Before the dashboard |
| I12 | Info | README.md, RESULTS.md and OPEN_QUESTIONS.md describe the as-received state (171 tests, "RAG/LLM not built"). | | Update them when the team accepts the new modules |

## Generalisation (G02 hits)

`grep -niE 'drone|lidar|uav|formation|swarm' fss_py/` (core package; packs, scenarios, demo
and tests excluded):

| Hit | What | Action |
|---|---|---|
| `cli.py:6` | docstring example `--query "Why did Drone 474 leave formation?"` | Reworded (`deb9ebe`) |
| `cli.py:37` | `--schema` default `schemas/drone_v0.yaml` | Moved to configuration: `[tool.fss] default_schema` in `pyproject.toml`. The value stays CWD-relative, so behaviour is unchanged (characterised by `test_cli.py` first, `54233ee`). |
| `schema.py:81` | docstring example `"LIDAR_STATUS"` | Reworded (`deb9ebe`) |
| `evidence.py:3` | "in**formation**" | False positive. The G02 test anchors at a word start and documents this case. |

Outside the core package, `streamlit_app.py` has 21 matching lines (I7).

Results:

- **G01:** the same `run_scenario → investigate` code path ran all eight scenarios over the
  five packs.
- **G03:** D2 (little-endian) and D4 (big-endian) decoded from one combined registry.
- **G04:** a copied pack directory was discovered and investigated end to end with no code.

## Pass criteria

Run 2 (`70285bd`), against the criteria of the second verification brief.

| Criterion | Result |
|---|---|
| Every SPEC item PASS or justified | ✅ SPEC-01 to 24 PASS; SPEC-23 envelope part justified (D13) |
| RAG-01, 02, 05, 07, 09 pass | ✅ (all of RAG-01 to 14 pass) |
| All non-live tests pass or are justified xfails | ✅ 501 passed, 0 failed, 0 xfail; the 8 skipped are live |
| Branch coverage ≥ 85 % on decoder, schema, knowledge, evidence | ✅ 95.8 / 87.5 / 92.5 / 100 |
| Demo files exist and match real runs | ✅ `demo/outputs/*.md` written by `demo/build_outputs.py` during the run; `run_demo.py SC1 SC2 SC5 SC6 SC7 Y02` exit 0, empty stderr |
| LLM-EVAL | Not run: no `FSS_LLM_API_KEY` |

Run 1's criteria (hard rules 1, 3, 5, 8-14, 16 each with a passing test; G01-G04) still hold:
the tests are unchanged and passed in run 2.
