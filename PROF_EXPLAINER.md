# The Failure Synthesis System, explained (about 10 minutes)

**Scope of this explainer.** It covers the **Python intelligence layer**: decoding,
evidence, domain knowledge, LLM synthesis and validation. The **Java evidence core** (ingest,
crash-tolerant storage, recovery, bounded retrieval) is a teammate's work in progress. Here it
is replaced by `MockRetriever`, which enforces the same retrieval contract over recorded
binary events.

**Where the numbers come from.** Every number below comes from the verification run of
2026-10-09 on an AWS EC2 instance (Ubuntu 26.04, 8 vCPU, Python 3.14.4), at commit `70285bd`.

---

## 1. The problem

**The drone example.**

- In a formation of drones, drone 474 suddenly leaves its slot. Its own logs show an
  *avoidance manoeuvre* for collision risk, then *left formation*.
- The cause is not on 474. About 70 ms earlier (by drone 298's clock), drone 298's LiDAR
  timed out, so its obstacle picture went stale and it drifted.
- An investigator who only reads drone 474's logs sees the symptom and misses the cause.

**A non-drone example (microservices).**

- A payment service starts returning HTTP 504 errors. Its logs say "upstream timeout".
- The real cause is two hops away: the database proxy's connection pool was exhausted, so
  order-service slowed down, so payment-service gave up waiting.
- This "visible failure ≠ cause" pattern appears in real public postmortems.
  `IRL_SIGNIFICANCE.md` lists twelve, from AWS, Cloudflare, Google Cloud, NPCI's UPI outage
  and others.

**Why this is hard**, beyond "look at more logs":

1. **Evidence is spread across many producers**, and their clocks are not synchronised.
2. **Telemetry is binary**: offsets, integer widths, byte order. An LLM asked "what do bytes 4–7
   mean?" will produce a fluent guess.
3. **Evidence can be lost exactly when it matters**, for example when the logger itself
   crashes. That is the Java core's job (§2).

## 2. Architecture: evidence, interpretation, reasoning

```
Producers ──► [Evidence layer: Java, teammate's in-progress work]
                ingest → crash-tolerant store → recovery → bounded retrieve()
          ──► [Interpretation layer: Python, deterministic]
                schema decode → enum labels → evidence → domain knowledge (RAG)
          ──► [Reasoning layer: Python + LLM]
                four-part context → LLM → validator → report
```

Each boundary has one rule:

- **Evidence** decides *what exists* and returns complete events in a **bounded time window**,
  optionally across **all** sources. It never interprets payload bytes.
- **Interpretation** is deterministic code plus configuration. The same bytes and the same
  schema always give the same result.
- **Reasoning** (the LLM) only sees decoded values and documented meaning, and must say what
  it doesn't know. A validator checks its answer against the evidence it was given.

`retrieve(source | ALL, t_start, t_end, event_type?, max_events)` is the only way in.

- Requests without a window are impossible to express.
- Windows over one hour are **rejected, not clamped**.
- This applies even when the LLM asks for more context mid-investigation.

## 3. Three epistemic levels, and why the LLM never sees bytes

Every fact handed to the LLM is labelled with one of three levels:

| Level | Comes from | Example | The LLM may… |
|---|---|---|---|
| **Decoded** | Deterministic decoding with a YAML schema | `timeout_count = 3` | treat it as fact |
| **Documented** | An enum map in the schema, or a domain document with its id | `17 = LIDAR_TIMEOUT` | use it as documented meaning |
| **Unknown** | No schema for the type, bytes outside any field, truncated payloads, undocumented values | "8 bytes … not configured" | only report it as a data gap |

**The LLM never sees bytes.** The decoder does all byte work: it bounds-checks before every
read, and uses explicit size, signedness and endianness from the schema.

- An event type with no schema becomes `UNKNOWN_EVENT_TYPE`. Its bytes stay in storage and are
  never sent.
- A payload too short for its schema becomes `MALFORMED_PAYLOAD`, with a reason naming the
  field, and no values.
- Extra trailing bytes become `PARTIALLY_DECODED` with a byte count.

A test (V01) searches every LLM context for every raw payload, in hex, base64 and as a byte
list, and finds none.

## 4. How RAG is used, and how it is restricted

**What documents are for.** Domain documents (manuals, error-code tables, state descriptions,
architecture notes, protocol notes, failure modes) say *what decoded values mean*. They never
take part in decoding: deleting the whole corpus left all 109 decoded events in the eight
scenarios byte-identical (RAG-01).

**The restrictions:**

- **Enum maps come first.** A code with a mapping in the schema is resolved in the decoder.
  A document can explain it but cannot override it. If a document *disagrees* with the map,
  or with another document, both are shown with their sources and a conflict warning
  (RAG-02, RAG-08).
- **Retrieval is driven by the evidence.** A document chunk is a candidate only if it explains
  a term actually present in the decoded evidence (an event name or a documented label), or a
  code value present in it. The investigator's question only re-ranks those candidates, so a
  question can never pull in unrelated documents (RAG-05).
- **Every snippet carries provenance** (document id, chunk id, kind, domain) and the tag
  *documented*, never *decoded* (RAG-09).
- **Absence is reported.**
  - A value with no documentation is marked undocumented, and the LLM is told not to explain
    it (RAG-07).
  - If nothing matches, the context says "no domain documentation found" (RAG-12).
- **Bounded:** at most `top_k` = 8 chunks, and any cut is reported (RAG-11).
- **Deterministic:** no embedding model is used. Matching is exact-term, so the same evidence
  always retrieves the same chunks in the same order (RAG-06).

**Retrieval quality**, on 25 hand-labelled queries across all five domains, with every
domain's documents loaded together:

| k (chunks) | precision@k | recall@k |
|---|---|---|
| 3 | 0.913 | 0.955 |
| 5 | 0.890 | 1.000 |

## 5. What was tested, with the real numbers

| Item | Result |
|---|---|
| Test cases (EC2 run, commit `70285bd`) | **509: 501 passed, 0 failed, 0 xfail, 8 skipped.** The 8 skipped are live-LLM tests: no API key was available. |
| Catalogue (`TEST_CASES.md`) | All 123 non-live IDs PASS. LLM-EVAL (7 metrics) was **not run**. |
| Specification conformance | SPEC-01 to SPEC-24 all PASS. SPEC-23's envelope part is justified as Java-side. |
| RAG conformance | RAG-01 to RAG-14: **14/14 PASS** |
| Branch coverage | decoder 95.8%, schema 87.5%, knowledge 92.5%, evidence 100%; 91.5% overall |
| Decode throughput (B04) | 97,447 / 96,882 / 97,290 events per second (3 runs, 100,000 events across five domains) |
| Domains | Five, through one unchanged code path: drones, microservices, industrial line, vehicle CAN (big-endian), warehouse robots |
| Property-based tests (B01–B03, hypothesis, fixed seed) | Random bytes against every schema, random valid schemas × random payloads: the decoder never raises, and SUCCESS always means zero unknown bytes |

**What the tests are:**

- The LLM in tests is a **deterministic stub** that returns the answer stored with each
  scenario. The scenarios therefore test everything *around* the LLM: retrieval, decoding,
  knowledge, context and validation.
- Some scenarios check that the validator *catches* a bad answer, such as a fabricated
  citation (Y02).
- How well a *real* LLM explains failures is the LLM-EVAL part, which still needs an API key.

## 6. Demo script (about 10 minutes)

On the EC2 instance:

```bash
cd ~/fss && source .venv/bin/activate
pytest -q                                    # 501 passed, 8 skipped
python demo/run_demo.py SC2                  # 1. microservices
python demo/run_demo.py SC1                  # 2. drones
python demo/run_demo.py SC5 --short          # 3. clock skew
python demo/run_demo.py SC6 SC7 --short      # 4. negative controls
python demo/run_demo.py Y02                  # 5. hallucination caught
python demo/run_demo.py G01                  # 6. domain swap
```

Each scenario prints eight parts:

1. the question;
2. the retrieval call;
3. the events with their epistemic tag;
4. data gaps;
5. retrieved knowledge with provenance;
6. the exact LLM context;
7. the synthesis;
8. the validator verdict.

The same reports are in `demo/outputs/` as markdown.

**What to point at:**

1. **SC2.**
   - The question is about payment-service (source 2), but retrieval uses `source=ALL`.
   - The cited cause is on the database proxy (source 3).
   - The retrieved documents include the architecture note that explains the dependency chain.
2. **SC1.**
   - The DIAGNOSTIC row is tagged `decoded + documented + unknown (8 bytes)`.
   - Part 4 says those 8 bytes were not decoded. They appear nowhere in part 6, the exact LLM
     context.
3. **SC5.**
   - AGV-7's `REPLAN` is stamped *before* AGV-12's battery stop, because AGV-7's clock is
     skewed.
   - The system keeps the raw stamps, states that timestamps cannot establish order, and
     reports low confidence.
4. **SC6/SC7.**
   - SC6 has only normal events: "No failure evidence found", no cause.
   - SC7 has only unknown event types: "No event in this window could be decoded", no cause.
5. **Y02.**
   - A citation of a drone-901 event that was never retrieved is marked `✗ NOT IN EVIDENCE`.
   - Verdict: **REJECTED**, rule 1.
6. **G01.**
   - Five packs are discovered from a directory; one is big-endian.
   - All eight scenarios run through the same functions.
   - A domain is just YAML plus Markdown.

Then open `demo/outputs/RAG_conformance.md`. It shows four things, all computed when the file
was built: decoding unchanged without the corpus, the gold-set precision, an undocumented value
kept unknown, and a document conflict surfaced.

## 7. Honest limitations

- **No real LLM was evaluated.** `FSS_LLM_API_KEY` was not available, so LLM-EVAL-1 to 7 (root-cause
  accuracy, citation validity, clock humility, stability) are "not run". The live client is
  tested only against a fake API.
- **The validator checks form, not truth.**
  - It guarantees that citations exist, gaps are reported, cross-source claims mention clocks,
    and nothing rests on undecodable data.
  - It cannot prove the causal story is right.
  - Its text checks are pattern-based, so a cleverly paraphrased guess could slip through.
- **The scenarios are synthetic.** No public dataset labels cross-producer failure chains
  with clock skew; `IRL_SIGNIFICANCE.md` §2 describes the search. The scenarios'
  ground-truth causes are known because we wrote them.
- **The RAG layer is simple on purpose:**
  - exact-term matching, no embeddings;
  - the budget is a chunk count, not a token count;
  - a document that uses different words from the labels will not be found.
- **The Java evidence core is not part of these results.** Durability claims belong to the
  teammate's work and its own tests.
- **Code status.** The original team code covered decoding and evidence. The knowledge,
  synthesis, validator, presentation and pack-loading modules were added during verification,
  and the team should review them.

## 8. Likely questions, with short answers

1. **What if the LLM hallucinates?**
   Every cited event is matched against the evidence by source, producer timestamp and type.
   A citation that doesn't exist makes the whole answer **REJECTED** (Y02). An omitted data gap
   is restored, and a missing clock caveat is added. Invalid JSON gets one retry, then a
   structured failure instead of a crash (Y06).

2. **Why not let the LLM read the raw logs?**
   Because they're binary. Offsets, widths and byte order must be exact, and a model guesses.
   We decode deterministically from schemas and give the model only decoded values, documented
   meanings and an explicit list of what is unknown. The test V01 shows no raw payload ever
   reaches the model.

3. **How do you know the cause if the clocks aren't synchronised?**
   We don't *know* it from timestamps, and we say so. Order across sources is never asserted
   from producer time. A cross-source causal claim must carry a clock caveat, or the validator
   adds one. Confidence drops when the stamps contradict the story (SC5). The causal link has
   to rest on content, such as the same aisle or a documented dependency.

4. **Is this only for drones?**
   No. Five domains run through the same code with zero code changes (G01). A test checks the
   core package for drone vocabulary and finds none (G02). A new domain is a directory of YAML
   schemas plus Markdown documents (G04).

5. **What happens if the logger crashes?**
   That is the Java evidence core's responsibility. Its design writes CRC-framed records into
   fixed blocks and recovers a valid prefix of acknowledged events per source. It is a
   teammate's in-progress work and outside the numbers here. The Python side never reads
   storage files; it only receives complete events through `retrieve()`.

6. **What is RAG doing that the enum map doesn't?**
   The enum map turns `17` into `LIDAR_TIMEOUT` deterministically. Documents explain what
   `LIDAR_TIMEOUT` *means* for the system (a stale obstacle map, a possible drift). They can
   also define codes the schema doesn't map (MP §8: `planner_state 4 → avoidance manoeuvre`).
   Those meanings are always tagged *documented*, with their source.

7. **What if two documents disagree?**
   Both are shown with their ids, and the data-quality section reports a `KNOWLEDGE_CONFLICT`.
   The system never picks one silently (RAG-08).

8. **What if a document says "ignore previous instructions"?**
   Documents are escaped, quoted line by line and wrapped as data, so they cannot create a fake
   section. Even if the model obeyed, the validator still rejects invented citations and
   restores omitted gaps (V08, RAG-13).

9. **Can the LLM ask for more data?**
   Once per investigation by default, and only through the same bounded `retrieve()`. "All
   history" or anything over one hour is rejected, never clamped. New events go through the
   same decoder, so an unknown type found in round two still lands only in the data gaps
   (PI-01 to PI-05).

10. **How would you evaluate a real LLM?**
    Run `python -m scenarios.llm_eval --runs 3` with an API key. It measures seven metrics,
    each before and after the validator:
    - root-cause attribution against the scenario's ground truth;
    - citation validity;
    - unknown preservation;
    - clock humility;
    - negative controls;
    - stability across runs;
    - validator interventions.

    The metric code is unit-tested on stub runs. The live numbers have not been produced yet.
