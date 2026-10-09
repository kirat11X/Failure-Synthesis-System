# Failure Synthesis System: first prototype (M0, P1, J1)

A crash-tolerant event store (Java) plus a deterministic decoding and evidence layer (Python)
for investigating failures in multi-drone fleets. This repo covers three milestones:

| Milestone | What | Where |
|---|---|---|
| **M0** | Frozen contract v0, golden fixtures, shared test vectors | `contract/`, `fixtures/` |
| **P1** | Python decoder: MockRetriever, YAML schemas, decoder, evidence builder | `fss_py/`, `schemas/`, `tests/` |
| **J1** | Java single-writer block store, crash recovery, bounded retrieval, crash harness | `fss-core/` |

Not built yet (by design): RAG, LLM calls, the dashboard, network ingest, time segments, block indexing.

- Results: [RESULTS.md](RESULTS.md)
- Mentor demo: [DEMO.md](DEMO.md)
- Open questions and next step: [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md)

```
contract/CONTRACT.md          frozen v0 contract (envelope, record, blocks, retrieve, decoding, durability)
contract/vectors/*.tsv        CRC-32C / envelope / reject vectors, shared by Java and Python
fixtures/generate_fixtures.py independent oracle: writes golden .bin + expected DecodedEvent JSON + vectors
fixtures/golden/*.bin         envelope streams (wire format, not storage files)
fixtures/expected/*.json      expected decoder output (+ clock-skew ground truth)
schemas/drone_v0.yaml         decoder schema for the fixture fleet
fss_py/                       contract, model, wire, schema, decoder, retriever, evidence, cli
tests/                        pytest suite (171 tests)
fss-core/                     Maven module: EnvelopeCodec, BlockStore, RecoveryManager, crash harness
```

## Setup

**Python 3.11+** with PyYAML and pytest:

```bash
python -m pip install -r requirements.txt
```

**JDK 21 and Maven 3.9+.** You need a full JDK 21. Fedora's `java-25-openjdk` package ships
without `lib/ct.sym`, so `javac --release 21` fails with "release version 21 not supported". On
this machine, point Maven at the Temurin 21 install:

```bash
export JAVA_HOME=~/.local/temurin-21       # or any JDK 21 (e.g. dnf install java-21-openjdk-devel)
sudo dnf install maven                      # or unpack apache-maven-3.9.x and add bin/ to PATH
```

## Run

| What | Command (from the repo root) |
|---|---|
| Check that fixtures and vectors are current | `python fixtures/generate_fixtures.py --check` |
| Regenerate fixtures and vectors | `python fixtures/generate_fixtures.py` |
| Python tests (M0 + P1) | `python -m pytest` |
| Longer fuzz run | `FSS_FUZZ_ITERATIONS=300000 FSS_FUZZ_SEED=1 python -m pytest tests/test_fuzz.py` |
| Demo: fixture → decoder → evidence | see [DEMO.md](DEMO.md), or `python -m fss_py --help` |
| Java tests (J1, includes quick crash tests) | `cd fss-core && mvn test` |
| Full crash harness | `cd fss-core && ./crash-harness.sh` |

`./crash-harness.sh` defaults to 60 SIGKILL runs, a truncation at every one of 327,681 byte
offsets, and 64,816 bit-flip trials. It takes about 30 s and ends with a markdown results table.
Useful options:

```bash
./crash-harness.sh --tests a --kill-chains 40          # only the kill test, 200 runs
./crash-harness.sh --tests bc --flips 100000           # only the sweeps, more random flips
./crash-harness.sh --dir /some/disk/path --tests a     # run on a real filesystem
```

By default the harness works under `java.io.tmpdir`, which is tmpfs here. The sweeps rewrite a
320 KiB file hundreds of thousands of times, so don't point `--dir` at an SSD for `--tests bc`.

## Where the hard rules are enforced

| Rule | Enforcement | Test |
|---|---|---|
| Java never interprets payload bytes | `EnvelopeCodec` reads only the 24-byte header; the payload is copied | `ContractVectorsTest` |
| Python never reads Java storage files | `fss_py` has an envelope decoder only (no record reader); `MockRetriever` rejects framed records | `test_rule_01_*` |
| Every retrieval is time-bounded | `RetrieveRequest` (Java) and `RetrievalRequest` (Python) reject inverted, empty, > 1 h and whole-u64 windows; `max_events` is 1..10 000 | `RetrieveContractTest`, `test_rule_03_*` |
| Unknowns stay unknown | `UNKNOWN_EVENT_TYPE`, `PARTIALLY_DECODED` and `MALFORMED_PAYLOAD` (all-or-nothing); reserved `UNKNOWN` enum label; opaque bytes never reach the evidence | `test_rule_10..13`, `test_fuzz.py` |
| Producer timestamp preserved; no global order | Raw `timestamp_ns` end to end, unsigned compares; evidence grouped by source plus a clock caveat | `test_rule_05/06`, `clock_skew_pair` fixture |

## Notes

- The repository root that git sees is your home directory. Nothing has been committed. Run
  `git init` in this folder if you want this project tracked on its own; `.gitignore` is ready.
- Contract changes from the proposal text (with reasons) are listed in
  [contract/CONTRACT.md §10](contract/CONTRACT.md).
