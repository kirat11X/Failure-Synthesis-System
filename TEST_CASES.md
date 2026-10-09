# FSS: Python Layer Test Cases

> **Filled by the verification run of 2026-10-09** on the EC2 instance (Ubuntu 26.04, 8 vCPU,
> Python 3.14.4), commit `70285bd`, no Java process running. Totals: **509 test cases: 501
> passed, 0 failed, 0 xfail, 8 skipped** (the live-LLM tests; `FSS_LLM_API_KEY` was not set).
> Every non-live ID below has at least one passing test; LLM-EVAL was not run. Per-category
> totals and coverage: `demo/outputs/summary.md`. Deviations D1–D9 and open issues:
> `VERIFICATION_REPORT.md`.

**Scope:** the Python intelligence layer only: retriever interface, schema packs, deterministic decoder, enum resolution, domain knowledge/RAG, evidence builder, LLM synthesis, output validator and presentation. The Java event core is being built separately by a teammate and is out of scope. All tests run against `MockRetriever` and fixtures.

**Specification sources** (the left column of every traceability table):

| Tag | Document |
|---|---|
| **HO §n** | *Python Implementation Handoff* (python_side.pdf), section n |
| **MP §n** | *Minor Project: Failure Synthesis System*, section n |
| **SRS FR/NFR-n** | *SE Lab Submission: SRS*, functional / non-functional requirement n |
| **HR n** | Hard rule n (HO §22) |

**Columns:**
- *Result*: PASS / FAIL / XFAIL / NOT-IMPL, filled by the verification run.
- *Evidence*: the test function name and, where relevant, the output file.

**Conventions:**
- Unit and scenario tests use a **stub LLM**: deterministic, no network.
- Tests marked **[LIVE]** call a real LLM. They are skipped when `FSS_LLM_API_KEY` is unset.
- Test function names start with the case ID, e.g. `test_P08_gap_bytes_partial`.

---

## 0. Specification conformance (from the initial PDFs)

These are the "is it built as specified?" checks. Each row must point to the implementing code *and* a passing test.

| ID | Requirement (source) | How it is verified | Result | Evidence |
|---|---|---|---|---|
| SPEC-01 | The decoder is the first stage after retrieval; the LLM does no binary decoding (HO §6, HR 8–9) | Trace the call graph: retriever → decoder → evidence → LLM. No code path sends `payload_bytes` to the LLM. V01 passes. | PASS | `test_SPEC01_decoder_first_and_no_payload_path_to_the_llm`. `investigate.py` decodes before building the context; no `payload_bytes` reference in context/synthesis/llm/validator/investigate/presentation; V01 |
| SPEC-02 | Schema per event type with name, offset, type, size, endian (HO §7) | Inspect the schema loader. S-series passes. | PASS | `test_SPEC02_schema_fields_carry_name_offset_type_size_endian`. `schema.py` FieldDef + validation; S01–S11 |
| SPEC-03 | Primitives u8–u64, i8–i64, f32, f64, bool; explicit signedness and endianness; no guessing (HO §8) | P01–P03 pass | PASS | `test_SPEC03_primitives_signedness_endianness_explicit`. P01–P03 (82 cases). Type names are `u8…u64, i8…i64, f32, f64, bool` (deviation D3) |
| SPEC-04 | Enum maps from config; unmapped value → `UNKNOWN` (HO §9) | E01–E04 pass | PASS | `test_SPEC04_enum_maps_from_configuration_and_unknown`. E01–E04 |
| SPEC-05 | Unknown type → `UNKNOWN_EVENT_TYPE`, `fields = {}`, raw kept but not sent to the LLM (HO §10, HR 10) | ST03, V02 pass | PASS | `test_SPEC05_unknown_type_kept_but_not_sent_to_the_llm`. ST03, V02 |
| SPEC-06 | Known prefix decoded, opaque tail counted → `PARTIALLY_DECODED`, `unknown_bytes = n` (HO §11, HR 11) | P08, P09, ST02 pass | PASS | `test_SPEC06_known_prefix_decoded_opaque_tail_counted`. P08, P09, ST02 |
| SPEC-07 | Bounds check before every read → `MALFORMED_PAYLOAD` + reason; no invented value (HO §12) | P05, P07, ST04, B02 pass | PASS | `test_SPEC07_bounds_checked_malformed_with_reason_no_invented_value`. P05, P07, ST04, B02. Policy: fields before a malformed field are discarded (all-or-nothing) |
| SPEC-08 | `DecodedEvent` carries source_id, timestamp, event_type, fields, decode_status, warnings (HO §13) | Schema test on the dataclass/JSON | PASS | `test_SPEC08_decoded_event_carries_the_handoff_fields`. `model.DecodedEvent`; timestamp key is `timestamp_ns`, u64 ns (deviation D1) |
| SPEC-09 | Three confidence levels: decoded / documented / unknown, kept distinct (HO §14, MP §8) | V10, RAG-09 | PASS | `test_SPEC09_three_epistemic_levels_kept_distinct`. V10, RAG-09 |
| SPEC-10 | Domain knowledge kept separate from schemas: the schema says *how* to decode, docs say *what* values mean (HO §15, MP §8) | RAG-01, RAG-02 | PASS | `test_SPEC10_knowledge_is_separate_from_schemas`. RAG-01, RAG-02 |
| SPEC-11 | Knowledge corpus can hold error codes, protocol docs, manuals, state descriptions, architecture docs, failure modes (HO §15) | RAG-03 | PASS | `test_SPEC11_corpus_holds_all_six_document_kinds`. RAG-03; all six kinds exist in the shipped packs |
| SPEC-12 | RAG retrieves relevant knowledge *together with* the event evidence (MP §8) | RAG-04 to RAG-06 | PASS | `test_SPEC12_knowledge_retrieved_together_with_evidence`. RAG-04 to RAG-06 |
| SPEC-13 | Undocumented value → uncertainty preserved, no invented meaning (MP §8) | RAG-07, Y04 | PASS | `test_SPEC13_undocumented_value_keeps_its_uncertainty`. RAG-07, Y04 |
| SPEC-14 | The LLM reasons and synthesises only; it doesn't establish raw-data meaning (HO §16, HR 14) | Y04, LLM-EVAL-3 | PASS | `test_SPEC14_llm_only_synthesises`. Y04; LLM-EVAL-3 not run (no key) |
| SPEC-15 | Progressive investigation: extra context only through bounded retrieval with limits enforced (HO §17, MP §9) | PI-01 to PI-05 | PASS | `test_SPEC15_extra_context_only_through_bounded_retrieval`. PI-01 to PI-05. Policy: windows over 1 h are rejected, never clamped; 1 context request per investigation by default |
| SPEC-16 | Cross-agent retrieval with `ALL`; no hard-coded source relationships (HO §18, HR 15) | R05, G02, SC1–SC5 | PASS | `test_SPEC16_cross_agent_retrieval_with_all`. R05, G02, SC1–SC5 |
| SPEC-17 | No clock synchronisation assumed; uncertainty stated (HO §19) | V05, Y05, SC5 | PASS | `test_SPEC17_no_clock_sync_assumed`. V05, Y05, SC5 |
| SPEC-18 | LLM context = query + decoded events + domain knowledge + data-quality warnings (HO §20) | V09 | PASS | `test_SPEC18_context_has_the_four_handoff_parts`. V09 |
| SPEC-19 | Output contract: summary, contributing_events, likely_cause, confidence, uncertainty, data_gaps (HO §21) | Y01 | PASS | `test_SPEC19_output_contract_matches_handoff_21`. Y01. `likely_cause` may be null for "no cause asserted" (deviation D9) |
| SPEC-20 | Investigator receives events, context, interpreted info, synthesis, and explicit unknowns (SRS FR-13, MP §10) | UI-01 to UI-05 | PASS | `test_SPEC20_investigator_receives_everything`. UI-01 to UI-05 |
| SPEC-21 | The AI layer is never required to infer unexplained raw fields (SRS NFR-09) | V01, Y04 | PASS | `test_SPEC21_ai_never_has_to_infer_raw_fields`. V01, Y04 |
| SPEC-22 | Separation: retrieval / deterministic interpretation / reconstruction / AI reasoning (SRS NFR-10) | Module dependency check (ARCH-01) | PASS | `test_SPEC22_separation_of_layers`. ARCH-01 |
| SPEC-23 | Different deployments can use different envelopes and schemas (SRS NFR-08, MP §4) | G01–G04 | PASS | `test_SPEC23_deployments_use_their_own_schemas`. G01–G04. **Justified:** schemas, enum maps and documents are per deployment; the envelope layout is fixed by contract v0 at the Java ingest, and Python consumes `EventRecord`s, so per-deployment envelopes are outside the Python layer |
| SPEC-24 | Python works independently of Java via mock records (HO §23 milestone order) | The whole suite runs with no Java process | PASS | `test_SPEC24_python_runs_without_java`. Suite run on EC2 with no Java process (run log: `java processes: none`); MockRetriever + fixtures only |

---

## 1. Primitive decoding (P)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| P01 | Every integer type × {little, big} × {min, 0, max}: 48 parametrised cases | Exact values | PASS | `test_P01_every_integer_type_endian_and_extreme` |
| P02 | float32/float64: normal, ±0, ±inf, NaN | Valid JSON output; documented non-finite policy plus a warning | PASS | `test_P02_floats_normal_signed_zero_and_non_finite`. Policy: NaN/±inf kept, one warning, serialised as JSON strings "NaN"/"Infinity"/"-Infinity"; −0.0 kept |
| P03 | boolean bytes 0x00 / 0x01 / 0x02 | false / true / documented policy (warning if non-canonical) | PASS | `test_P03_boolean_bytes`. Policy: 0x02 makes the whole event MALFORMED_PAYLOAD with a reason; not coerced (deviation D8) |
| P04 | Field ending exactly at the payload end | SUCCESS | PASS | `test_P04_field_ending_exactly_at_payload_end` |
| P05 | Payload one byte short of the last field | MALFORMED_PAYLOAD; reason names the field, the required range and the available range | PASS | `test_P05_payload_one_byte_short_of_last_field`. Reason names the field and the required range; the available range is given as the payload length (deviation D4) |
| P06 | Empty payload, schema with zero fields | SUCCESS | PASS | `test_P06_zero_length_payload_zero_field_schema` |
| P07 | Empty payload, schema with fields | MALFORMED_PAYLOAD | PASS | `test_P07_zero_length_payload_schema_with_fields` |
| P08 | 3-byte gap between two fields | PARTIALLY_DECODED, unknown_bytes = 3 | PASS | `test_P08_gap_bytes_partial` |
| P09 | 8 trailing opaque bytes (the HO §11 example) | PARTIALLY_DECODED, unknown_bytes = 8 | PASS | `test_P09_trailing_opaque_bytes_partial` |
| P10 | 64 KiB payload with fields near the end | Correct values | PASS | `test_P10_max_payload_fields_near_the_end`. Run at 65,504 bytes, the largest legal payload; 65,536 is rejected by contract |

## 2. Schema validation (S)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| S01 | Overlapping fields | Load error naming both fields | PASS | `test_S01_overlapping_fields_error_names_both` |
| S02 | `uint32` declared with size 2 | Load error | PASS | `test_S02_u32_declared_with_size_2`. Written with the code's type name `u32` (deviation D3) |
| S03 | Unknown type `uint24` | Load error | PASS | `test_S03_unknown_type` |
| S04 | Negative offset | Load error | PASS | `test_S04_negative_offset` |
| S05 | Duplicate field name | Load error | PASS | `test_S05_duplicate_field_name` |
| S06 | Same event_type in two files | Load error | PASS | `test_S06_same_event_name_in_two_files`, `test_S06_same_event_type_in_two_files`. Pack loader names both files |
| S07 | `endian: middle` | Load error | PASS | `test_S07_invalid_endianness` |
| S08 | Enum on a float field | Load error | PASS | `test_S08_enum_on_float_field` |
| S09 | YAML with a `!!python/object` tag | Rejected; nothing executed | PASS | `test_S09_python_object_tag_rejected_and_not_executed` |
| S10 | Empty schema pack | Loads; every event is UNKNOWN_EVENT_TYPE | PASS | `test_S10_empty_pack_loads_and_everything_is_unknown`, `test_S10_schema_file_with_no_event_types_is_still_rejected`. An empty pack directory loads; an empty schema *file* is rejected (deviation D7) |
| S11 | Offset 2^40 | Load error or MALFORMED; never an overflow or crash | PASS | `test_S11_huge_offset_is_a_load_error_not_an_overflow` |

## 3. Enums (E)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| E01 | 17 with a map entry `17 → LIDAR_TIMEOUT` | `status_name = LIDAR_TIMEOUT` | PASS | `test_E01_mapped_value` |
| E02 | 99 with no mapping | `UNKNOWN`, raw 99 kept | PASS | `test_E02_unmapped_value_stays_unknown_and_raw_is_kept` |
| E03 | Enum on a signed field, value −1 | Correct lookup | PASS | `test_E03_enum_on_signed_field_negative_value` |
| E04 | Change only the YAML map | Output changes with no code change | PASS | `test_E04_enum_map_edited_in_yaml_only` |

## 4. Status aggregation (ST)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| ST01 | Full coverage | SUCCESS, unknown_bytes = 0 | PASS | `test_ST01_full_coverage_success` |
| ST02 | Fields plus opaque tail | PARTIALLY_DECODED | PASS | `test_ST02_fields_plus_opaque_tail_partial` |
| ST03 | Type 0x31 with no schema | UNKNOWN_EVENT_TYPE, `fields = {}` | PASS | `test_ST03_unknown_type_0x31` |
| ST04 | Truncated field | MALFORMED_PAYLOAD + reason | PASS | `test_ST04_truncated_field_malformed_with_reason` |
| ST05 | Opaque tail **and** truncated field | MALFORMED_PAYLOAD (precedence) | PASS | `test_ST05_opaque_region_and_truncated_field_malformed_wins` |

## 5. Retrieval contract on the Python side (R)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| R01 | Missing start or end | Rejected | PASS | `test_R01_missing_start_or_end_rejected` |
| R02 | `end <= start` | Rejected | PASS | `test_R02_end_not_after_start_rejected` |
| R03 | Events exactly at start and at end | Matches the documented interval semantics | PASS | `test_R03_interval_is_half_open`. Half-open `[start, end)` |
| R04 | Single-source filter | Only that source | PASS | `test_R04_single_source_filter` |
| R05 | `source = ALL` | All sources in the window | PASS | `test_R05_all_sources_in_window` |
| R06 | event_type filter | Only that type | PASS | `test_R06_event_type_filter` |
| R07 | 500 matches, max_events = 100 | Exactly 100, `truncated = true` | PASS | `test_R07_500_matching_max_events_100` |
| R08 | Empty window | `[]`, `truncated = false` | PASS | `test_R08_empty_window` |
| R09 | Shuffle the retriever output order | Identical downstream evidence JSON | PASS | `test_R09_shuffled_retrieval_gives_identical_evidence_json` |
| R10 | Static check | Decoder, knowledge, evidence and synthesis modules do no file/storage I/O on event data | PASS | `test_R10_static_no_file_or_storage_access`. AST check of every module except the I/O allowlist (retriever, schema, packs, cli) |

## 6. Evidence builder (V)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| V01 | Search the full LLM context for each raw payload as hex, base64 and Python bytes repr | Not found | PASS | `test_V01_no_raw_payload_bytes_in_any_context` |
| V02 | Unknown type present | Appears only in the data-gaps section | PASS | `test_V02_unknown_type_listed_in_data_quality_only`. In the LLM context. `build_evidence`'s dict also lists them with `fields = {}` (deviation D6) |
| V03 | Partial event | Gap entry with byte count, e.g. "8 bytes … not configured/documented" | PASS | `test_V03_partial_event_gap_has_byte_count`. "8 payload bytes of DIAGNOSTIC … were not decoded because their structure is not configured." |
| V04 | Malformed event | Gap entry with field and reason | PASS | `test_V04_malformed_event_gap_has_reason` |
| V05 | 1 source vs ≥2 sources | Clock caveat absent vs present | PASS | `test_V05_clock_caveat_only_with_several_sources` |
| V06 | Timestamps | Unchanged values, labelled as producer time | PASS | `test_V06_timestamps_labelled_as_producer_time_and_unchanged` |
| V07 | Same input twice | Byte-identical context | PASS | `test_V07_same_input_gives_byte_identical_context` |
| V08 | Domain document containing "ignore previous instructions" | Delimited as data; validator still enforces the contract | PASS | `test_V08_document_injection_is_delimited_as_data`, `test_V08_validator_still_enforces_the_contract` |
| V09 | Context structure | Exactly 4 parts: query, decoded events, domain knowledge, data quality (HO §20) | PASS | `test_V09_context_has_exactly_four_parts` |
| V10 | Each fact in the context | Tagged decoded / documented / unknown (HO §14) | PASS | `test_V10_every_fact_in_the_context_is_tagged` |

## 7. Domain knowledge and RAG (RAG)

This section is the main check that the RAG layer matches the initial PDFs (HO §15, MP §8).

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| RAG-01 | Delete the whole knowledge corpus, then decode all fixtures | `DecodedEvent` output **unchanged**: RAG is never used for decoding | PASS | `test_RAG01_deleting_the_corpus_does_not_change_decoding` |
| RAG-02 | Enum map says `17 → LIDAR_TIMEOUT`; the corpus also contains a document about LIDAR_TIMEOUT | Code resolved by the enum map; the document only adds explanation | PASS | `test_RAG02_enum_map_resolves_the_code_document_only_explains` |
| RAG-03 | Corpus with 6 document kinds: error-code table, protocol doc, manual, state descriptions, architecture doc, failure-mode doc | All ingest; each chunk keeps doc id, kind, domain and chunk id | PASS | `test_RAG03_six_document_kinds_ingest_with_chunk_provenance`. Chunk ids `<doc>#n`; kind, domain, doc id kept |
| RAG-04 | Evidence contains LIDAR_TIMEOUT, AVOIDANCE, LEFT_FORMATION | Top-k includes the documents for those terms. Gold-set precision@k ≥ 0.8 (gold set in `tests/rag_gold.yaml`, ≥ 20 queries over D1–D5) | PASS | `test_RAG04_gold_set_precision_and_recall`, `test_RAG04_scenario_terms_retrieve_their_documents`. Gold set 25 queries, all domains loaded: precision@3 **0.913**, recall@3 0.955; precision@5 0.890, recall@5 1.000; `demo/outputs/RAG_conformance.md` |
| RAG-05 | The retrieval query is built from the evidence (event types, enum names) plus the user question, not the question alone | Inspect the query and assert evidence terms are present | PASS | `test_RAG05_query_is_built_from_evidence_plus_question`, `test_RAG05_question_changes_ranking_not_candidates`. Evidence terms decide candidates; question terms only re-rank |
| RAG-06 | Same evidence twice | Same chunks, same order (deterministic retrieval, fixed embedding model and seed) | PASS | `test_RAG06_retrieval_is_deterministic`. No embedding model: retrieval is exact-term, deterministic by construction |
| RAG-07 | Value with no documentation (e.g. `planner_state = 9`) | Context marks it "undocumented"; synthesis gives it no meaning | PASS | `test_RAG07_stub_synthesis_does_not_explain_the_unknown_label`, `test_RAG07_undocumented_value_is_marked_not_explained`. `[UNDOCUMENTED_VALUE]` in data quality; `demo/outputs/RAG_conformance.md` |
| RAG-08 | Two documents disagree on a code's meaning | Both shown with provenance and a conflict warning; not silently resolved | PASS | `test_RAG08_conflicting_documents_are_both_shown_with_a_warning`, `test_RAG08_document_disagreeing_with_the_enum_map_is_surfaced`. Doc vs doc and doc vs enum map; `[KNOWLEDGE_CONFLICT]`; `demo/outputs/RAG_conformance.md` |
| RAG-09 | Each knowledge snippet in the context | Carries provenance (doc id/chunk id) and is tagged *documented*, never *decoded* | PASS | `test_RAG09_every_snippet_has_provenance_and_the_documented_tag` |
| RAG-10 | D2 microservice scenario with every domain's docs loaded | No drone documents retrieved (domain isolation or relevance) | PASS | `test_RAG10_microservices_scenario_with_every_domain_loaded`. Isolation by relevance (domain keys are distinct), not by a domain filter |
| RAG-11 | Context budget: 200 relevant chunks | Capped at the configured top-k / token budget; truncation reported in data quality | PASS | `test_RAG11_context_budget_caps_chunks_and_reports_truncation`. Cap is a chunk count (`top_k`, default 8); there is no token budget (open issue) |
| RAG-12 | Empty retrieval (no relevant docs) | Pipeline continues; "no domain documentation found" in data quality | PASS | `test_RAG12_empty_retrieval_is_reported_and_the_pipeline_continues`. `[NO_DOMAIN_DOCUMENTATION]` in data quality |
| RAG-13 | Document contains prompt-injection text | Delimited as quoted data (see V08) | PASS | `test_RAG13_prompt_injection_in_a_document_is_quoted_data` |
| RAG-14 | Add a new domain document | Retrievable after re-indexing; no code change | PASS | `test_RAG14_new_document_retrievable_after_reload_without_code` |

## 8. Progressive investigation (PI)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| PI-01 | Stub LLM asks for "context 30 s before event X" | Converted into a `retrieve()` call with an explicit start and end | PASS | `test_PI01_context_before_event_becomes_a_bounded_retrieve` |
| PI-02 | Stub asks for an unbounded or "all history" window | Rejected; synthesis continues with the existing evidence and notes the refusal | PASS | `test_PI02_all_history_window_rejected_and_synthesis_continues`, `test_PI02_request_anchored_outside_the_evidence_rejected` |
| PI-03 | Stub asks for a window larger than the configured maximum | Clamped or rejected, per documented policy | PASS | `test_PI03_oversized_window_rejected_not_clamped`. Policy: rejected, never clamped |
| PI-04 | Stub keeps asking for more | Stops at the configured maximum number of rounds | PASS | `test_PI04_round_budget_enforced`. Default budget 1 request; a further request is a format error → one retry → final answer |
| PI-05 | Extra events from round 2 | Pass through the same decoder and evidence path (no shortcut to raw bytes) | PASS | `test_PI05_round_two_events_go_through_the_same_decoder_and_evidence_path` |

## 9. Synthesis and validator (Y), stub LLM

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| Y01 | Well-formed output | Passes the HO §21 schema | PASS | `test_Y01_fenced_json_is_accepted`, `test_Y01_schema_violations_are_format_errors` (+1) |
| Y02 | Cites an event not in the evidence | Rejected and flagged | PASS | `test_Y02_citation_not_in_evidence_rejected`, `test_Y02_right_event_wrong_timestamp_rejected` |
| Y03 | Omits a known data gap | Flagged; gap restored | PASS | `test_Y03_omitted_gap_flagged_and_restored`, `test_Y03_truncation_gap_must_be_reported` |
| Y04 | Interprets opaque bytes or an unknown type | Flagged | PASS | `test_Y04_citing_a_malformed_event_rejected`, `test_Y04_citing_an_unknown_type_event_rejected` (+2) |
| Y05 | Cross-source causal claim without a clock caveat | Flagged | PASS | `test_Y05_cross_source_claim_without_clock_caveat`, `test_Y05_single_source_claim_needs_no_caveat` |
| Y06 | Invalid JSON | One retry, then a structured failure; no crash | PASS | `test_Y06_invalid_json_twice_gives_structured_failure`, `test_Y06_invalid_then_valid_recovers_on_retry` (+1) |
| Y07 | `confidence: "very high"` | Rejected (enum low/medium/high) | PASS | `test_Y07_confidence_very_high_rejected` |

## 10. Presentation / dashboard output (UI)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| UI-01 | SC1 report | Contains all 5 MP §10 elements: explanation, supporting events, sources involved, time window, limitations | PASS | `test_UI01_sc1_report_has_the_five_mp10_elements` |
| UI-02 | Event type 0x31 with extra bytes | Shows the MP §10 style message: bytes preserved but not used for interpretation | PASS | `test_UI02_UI03_UI04_uninterpretable_data_is_shown`. Shown as "Uninterpreted data: … payload bytes were preserved but not interpreted" (MP §10 says "…not used for semantic interpretation") |
| UI-03 | Partial event | Shows "n bytes could not be interpreted because their structure is not configured/documented" (HO §11) | PASS | `test_UI02_UI03_UI04_uninterpretable_data_is_shown` |
| UI-04 | Malformed event | Shows which field could not be decoded and why (HO §12) | PASS | `test_UI02_UI03_UI04_uninterpretable_data_is_shown` |
| UI-05 | Report rendering | Markdown/HTML output saved to `demo/outputs/` | PASS | `test_UI05_reports_are_written_to_demo_outputs`. `demo/outputs/*.md` (TEST_CASES.md §15) |

## 11. Generalisation (G) and architecture (ARCH)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| G01 | D1–D5 packs through the same pipeline | All pass, zero code change | PASS | `test_G01_five_domains_through_the_same_pipeline` |
| G02 | grep the core package for `drone\|lidar\|uav\|formation\|swarm` | No hits outside packs, docs, examples and tests | PASS | `test_G02_no_domain_vocabulary_in_core_package`, `test_G02_pattern_is_word_anchored`. Word-anchored pattern; "information" is not a hit |
| G03 | D4 big-endian pack alongside little-endian packs | Both correct | PASS | `test_G03_big_endian_pack_alongside_little_endian_packs` |
| G04 | New pack directory dropped in | Auto-discovered | PASS | `test_G04_new_pack_directory_runs_end_to_end_without_code`, `test_G04_new_pack_directory_is_discovered_without_registration` |
| ARCH-01 | Import graph | decoder doesn't import llm/rag; rag doesn't import decoder internals; llm doesn't import retriever internals | PASS | `test_ARCH01_import_graph` |

## 12. End-to-end scenarios (SC)

Each scenario has a fixture generator, golden decoded events, golden evidence context and a golden stub synthesis. **[LIVE]** versions are saved for the professor demo.

| ID | Domain | Story | Proves | Result | Evidence |
|---|---|---|---|---|---|
| SC1 | D1 drones | 298 LiDAR timeout → 474 avoidance → 474 leaves formation; one diagnostic event has 8 opaque bytes | Cross-agent cause, gap reported, clock caveat | PASS | `test_SC1_drones_cross_source_cause_with_opaque_gap`. `demo/outputs/SC1_drone.md` |
| SC2 | D2 microservices | DB pool exhausted → order-service p99 spike → payment 504s | Visible failure ≠ cause; ALL retrieval | PASS | `test_SC2_microservices_failing_service_is_not_the_cause`. `demo/outputs/SC2_microservices.md` |
| SC3 | D3 industrial | Temp sensor drift on A → overheat interlock → conveyor B starved; vendor PLC type 0x7F unknown | Unknown preserved, not guessed | PASS | `test_SC3_unknown_vendor_type_preserved_and_reported_not_guessed` |
| SC4 | D4 vehicle (big-endian) | Wheel-speed ECU fault → ABS disabled → dash warning; one truncated frame | Endianness, malformed handling | PASS | `test_SC4_vehicle_big_endian_and_malformed_frame` |
| SC5 | D5 robots | AGV-12 battery critical → AGV-7 replans; AGV-7's clock skewed earlier | No causation inferred from timestamps alone | PASS | `test_SC5_clock_skew_is_kept_and_causation_not_inferred_from_timestamps`. `demo/outputs/SC5_clock_skew.md` |
| SC6 | any | Only normal events | "No failure evidence", low confidence | PASS | `test_SC6_only_normal_events_no_invented_cause`. `demo/outputs/SC6_SC7_negative.md` |
| SC7 | any | Only unknown event types | Evidence uninterpretable; no cause asserted | PASS | `test_SC7_only_unknown_types_evidence_uninterpretable`. `demo/outputs/SC6_SC7_negative.md` |
| SC8 | any | Retrieval truncated at max_events | "Retrieval truncated" reported as a data gap | PASS | `test_SC8_truncated_retrieval_reported_as_gap` |

## 13. Robustness and properties (B)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| B01 | Hypothesis: random bytes × every schema | Never raises; valid status | PASS | `test_B01_random_bytes_against_every_schema` |
| B02 | Every truncation length of every golden payload | Never SUCCESS below the required length | PASS | `test_B02_every_truncation_of_every_golden_payload`, `test_B02_random_schema_truncated_below_required_length` |
| B03 | Random valid schemas × random payloads | SUCCESS ⇒ unknown_bytes = 0; decoded fields ≤ schema fields | PASS | `test_B03_random_schemas_and_payloads_keep_invariants` |
| B04 | Decode 100k events | Throughput (events/s) recorded | PASS | `test_B04_decode_throughput_100k_events`. 97,447 / 96,882 / 97,290 events/s (3 runs, EC2, 8 vCPU, Python 3.14.4) |
| B05 | Fixed seed, rerun | Identical outputs | PASS | `test_B05_same_seed_same_output`, `test_B05_whole_pipeline_is_deterministic` |

## 14. Live-LLM evaluation (LLM-EVAL) [LIVE]

Run SC1–SC8, **3 runs each**, at temperature 0 (or the lowest the provider allows).

| ID | Metric | Definition | Target | Result |
|---|---|---|---|---|
| LLM-EVAL-1 | Root-cause attribution | `likely_cause` names the injected cause source and event (SC1–SC5) | ≥ 4/5 scenarios in every run | not run: no `FSS_LLM_API_KEY` |
| LLM-EVAL-2 | Citation validity | Share of contributing_events present in the evidence (before validator repair) | report % | not run: no `FSS_LLM_API_KEY` |
| LLM-EVAL-3 | Unknown preservation | No interpretation of opaque bytes, unknown types or undocumented values | 100% after validator | not run: no `FSS_LLM_API_KEY` |
| LLM-EVAL-4 | Clock humility | Caveat present whenever a cross-source causal claim is made | 100% after validator | not run: no `FSS_LLM_API_KEY` |
| LLM-EVAL-5 | Negative controls | SC6/SC7 assert no cause | 100% | not run: no `FSS_LLM_API_KEY` |
| LLM-EVAL-6 | Stability | Same cause across the 3 runs | report | not run: no `FSS_LLM_API_KEY` |
| LLM-EVAL-7 | Validator interventions | Number of flags or repairs per run | report | not run: no `FSS_LLM_API_KEY` |

---

## 15. Outputs prepared for the professors

| File | Content |
|---|---|
| `demo/outputs/SC1_drone.md` | Query → events table → data gaps → evidence context → synthesis → validator verdict |
| `demo/outputs/SC2_microservices.md` | Same layout; shows the system is domain-agnostic |
| `demo/outputs/SC5_clock_skew.md` | Shows the system refusing to over-claim causality |
| `demo/outputs/SC6_SC7_negative.md` | No invented failures |
| `demo/outputs/Y02_hallucination_caught.md` | Validator rejecting a fabricated citation |
| `demo/outputs/RAG_conformance.md` | RAG-01/04/07/08 side by side: decoding untouched, relevant docs retrieved, undocumented value kept unknown, conflict surfaced |
| `demo/outputs/summary.md` | Totals per category, coverage, LLM-EVAL table |
