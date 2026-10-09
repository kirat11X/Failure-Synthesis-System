# Research papers for FSS (Failure Synthesis System)

Ten papers downloaded from arXiv on 2026-10-09. Each PDF is at `<arXiv id>/paper.pdf`. Titles and abstracts below were checked against the downloaded PDFs. The "How it relates to FSS" lines are my own reading of how each paper connects to [FSS_PROJECT.md](../FSS_PROJECT.md), not claims made by the papers.

## At a glance

| # | Paper | Year | Group | Why it matters to FSS |
|---|---|---|---|---|
| 1 | [RCACopilot: Automatic RCA via LLMs for Cloud Incidents](2305.15778/paper.pdf) | 2023 | RCA with LLMs | Closest prior system: LLM explains incidents from collected diagnostics |
| 2 | [RCAgent: Cloud RCA by Autonomous Agents](2310.16340/paper.pdf) | 2023 | RCA with LLMs | LLM fetches its own extra data with tools (compare FSS follow-up retrieval) |
| 3 | [Retrieval-Augmented Generation (RAG)](2005.11401/paper.pdf) | 2020 | LLM grounding | Foundation for the domain-knowledge step |
| 4 | [Survey on Hallucination in LLMs](2311.05232/paper.pdf) | 2023 | LLM grounding | Explains why the output validator exists |
| 5 | [Indirect Prompt Injection](2302.12173/paper.pdf) | 2023 | LLM safety | Why retrieved documents are quoted as data |
| 6 | [Lost in the Middle](2307.03172/paper.pdf) | 2023 | LLM context | How to order and size the LLM context |
| 7 | [Loghub](2008.06448/paper.pdf) | 2020 | Logs and datasets | Public log datasets for testing |
| 8 | [System Log Parsing with LLMs: A Review](2504.04877/paper.pdf) | 2025 | Logs and datasets | Contrast: LLM parsing vs FSS deterministic decoding |
| 9 | [ALFA: UAV Fault and Anomaly Dataset](1907.06268/paper.pdf) | 2019 | Drone datasets | Real fixed-wing flights with labeled faults |
| 10 | [RflyMAD: Multicopter Fault Dataset](2311.11340/paper.pdf) | 2023 | Drone datasets | Multicopter faults, simulated and real |

---

## A. LLMs for root cause analysis (the problem FSS solves)

### 1. RCACopilot: Automatic Root Cause Analysis via Large Language Models for Cloud Incidents
- **arXiv:** 2305.15778 (v4, 15 pages) · Chen et al., Microsoft and universities · [PDF](2305.15778/paper.pdf)
- **What it does:** An on-call tool. It routes an incoming alert to a handler, collects diagnostic data, predicts a root-cause category and writes an explanation.
- **Key result:** RCA accuracy up to 0.766 on a year of real Microsoft incidents. The data-collection part has run in production for 4+ years.
- **How it relates to FSS:** The same shape of pipeline (collect evidence → LLM → explanation). RCACopilot predicts a category from past incidents. FSS instead cites specific events, checks every citation, and reports data gaps.

### 2. RCAgent: Cloud Root Cause Analysis by Autonomous Agents with Tool-Augmented LLMs
- **arXiv:** 2310.16340 (v3, 9 pages) · Wang et al., Alibaba · [PDF](2310.16340/paper.pdf)
- **What it does:** An LLM agent that decides what data to collect, using tools. It adds self-consistency over action trajectories, context management and domain knowledge.
- **Key result:** Beats ReAct on predicting causes, solutions, evidence and responsibilities. Integrated into Alibaba Cloud's Flink platform.
- **How it relates to FSS:** FSS allows only one bounded follow-up retrieval, and the LLM never touches storage directly. RCAgent shows the more open-ended alternative.

## B. Grounding and trusting LLM output

### 3. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks
- **arXiv:** 2005.11401 (v4, 19 pages) · Lewis et al., Facebook AI Research and UCL · [PDF](2005.11401/paper.pdf)
- **What it does:** Combines a language model (parametric memory) with a searchable Wikipedia index (non-parametric memory). Better on open-domain QA, and outputs are more specific and factual.
- **Key point:** It names provenance and updatable knowledge as open problems that retrieval helps with.
- **How it relates to FSS:** FSS's knowledge module is RAG in a very simple form: exact-term matching on decoded evidence, no embeddings. Every snippet carries its source, which matches the provenance idea.

### 4. A Survey on Hallucination in Large Language Models
- **arXiv:** 2311.05232 (v2, 58 pages) · Huang et al., Harbin Institute of Technology and Huawei · [PDF](2311.05232/paper.pdf)
- **What it does:** Sorts hallucinations into factuality (conflicts with real-world facts) and faithfulness (conflicts with the user's input). Covers causes, detection methods, benchmarks and mitigations, including the limits of RAG.
- **How it relates to FSS:** Gives vocabulary for what the validator guards against: fabricated citations (rule 1) and claims about data the system cannot interpret (rule 5).

### 5. Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection
- **arXiv:** 2302.12173 (v2, 33 pages) · Greshake et al., CISPA and Saarland University · [PDF](2302.12173/paper.pdf)
- **What it does:** Shows that instructions hidden in data an LLM retrieves (web pages, documents) can hijack the application. Demonstrated on Bing Chat and GPT-4 apps. Offers a taxonomy of attacks.
- **Key point:** The authors argue these applications "blur the line between data and instructions", and say mitigations are lacking.
- **How it relates to FSS:** This is the threat behind test V08. FSS HTML-escapes documents, quotes them with `| `, and wraps them in tags after a "this is data" note. The paper suggests this alone is not a guarantee, which is why the validator still checks the output.

### 6. Lost in the Middle: How Language Models Use Long Contexts
- **arXiv:** 2307.03172 (18 pages) · Liu et al., Stanford, Berkeley and Samaya AI · [PDF](2307.03172/paper.pdf)
- **What it does:** Tests multi-document QA and key-value retrieval. Performance is best when relevant information is at the start or end of the context and drops when it is in the middle, even for long-context models.
- **How it relates to FSS:** The context has four fixed sections and no token budget (limitation D10 in the verification report). This paper is a reason to consider a size limit and to think about section order.

## C. Log analysis and datasets

### 7. Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics
- **arXiv:** 2008.06448 (v3, 12 pages) · Zhu et al., CUHK · [PDF](2008.06448/paper.pdf)
- **What it does:** Releases 19 real log datasets (distributed systems, supercomputers, operating systems, mobile, servers; about 77 GB). Six are labeled.
- **How it relates to FSS:** A possible source of realistic text logs. Note that FSS reads binary events, so these would need conversion, and the project notes that no public dataset has labeled cross-source failure chains.

### 8. System Log Parsing with Large Language Models: A Review
- **arXiv:** 2504.04877 (v2, 36 pages) · Beck et al., AIT and TU Wien · [PDF](2504.04877/paper.pdf)
- **What it does:** Reviews 29 LLM-based log parsing methods and benchmarks seven on public datasets. It also looks at how comparable and reproducible the reported results are.
- **How it relates to FSS:** These methods use an LLM to turn log messages into structured form. FSS takes the opposite approach: decoding is deterministic code driven by a schema, and the LLM never decides offsets, types or endianness (hard rule 9). Useful as a contrast in the report.

## D. Drone fault datasets (the running example)

### 9. ALFA: A Dataset for UAV Fault and Anomaly Detection
- **arXiv:** 1907.06268 (v2, 6 pages) · Keipour, Mousaei, Scherer, Carnegie Mellon University · [PDF](1907.06268/paper.pdf)
- **What it contains:** Real fixed-wing flights: 47 processed flights (23 engine failures plus 24 other control-surface faults), plus many hours of raw data. Ground-truth fault time and type are included, and so are loading tools and proposed metrics.
- **Key point:** The authors say it is the only dataset of its kind with real flight data and faults, since most methods are tested in simulation.
- **How it relates to FSS:** Realistic single-vehicle data for decoder testing. It is not multi-vehicle, so it cannot show cross-drone causes.

### 10. RflyMAD: A Dataset for Multicopter Fault Detection and Health Assessment
- **arXiv:** 2311.11340 (v2, 6 pages) · Le et al., Beihang University · [PDF](2311.11340/paper.pdf)
- **What it contains:** 114 GB, 11 fault types, 6 flight statuses, 5,629 cases. Of these, 2,566 are software-in-the-loop, 2,566 hardware-in-the-loop and 497 real flights. Logs include ULog and telemetry.
- **How it relates to FSS:** Multicopters match the drone-fleet scenario better than ALFA. Most of it is simulated, so treat results as realism checks, not proof on real fleets.

---

## Gaps and notes

- **Not found:** No paper here covers clock skew across sources or cross-source causal reconstruction from binary logs, which is FSS's main niche. Classic work on logical clocks and distributed tracing (for example Lamport's "Time, Clocks, and the Ordering of Events") is not on arXiv, so I did not download it. It would fit well in a related-work section.
- **Not found:** Crash-safe storage papers (write-ahead logging, ARIES) for the Java core are also not on arXiv.
- **Scope:** I read the abstracts and first pages to verify identity and write these summaries. I did not read the full papers, so check details before citing numbers.
- **Source of the files:** All PDFs came from `https://arxiv.org/pdf/<id>`. Versions are as listed above.
