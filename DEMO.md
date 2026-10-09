# FSS demo: a 10-minute script

This script follows FSS_PROJECT.md §8.12. Every step uses the same pipeline on recorded
binary events:

```
envelope stream (.bin) → MockRetriever (bounded retrieve) → deterministic decoder
  → evidence → domain documents → LLM context → LLM → output validator
```

The LLM is a deterministic **stub** that returns the answer stored with each scenario, so the
demo is offline and repeatable. Everything around the LLM is the real system. `--live` swaps in.

Each scenario prints six numbered parts:

1. Query and retrieval window
2. Retrieved events
3. Data gaps
4. Evidence context (exactly what the LLM receives)
5. Synthesis
6. Validator verdict

## Before the session (2 minutes, not part of the 10)

```bash
ssh -i awss.pem ubuntu@ec2-3-229-124-202.compute-1.amazonaws.com
cd ~/fss && source .venv/bin/activate
pytest -q                      # expect: 445 passed, 8 skipped
```

Use a terminal at least 130 columns wide. For long output, pipe through `less -R`.

## 1. SC2: microservices (2 min). The system is not drone-specific, and the failing service is not the cause.

```bash
python demo/run_demo.py SC2
```

Point out:

- **[1]** The question is about **payment-service (source 2)**, but retrieval uses
  `source=ALL` over a 30 s window. Retrieving only source 2 would hide the cause; test SC2
  proves this.
- **[2]**
  - payment-service returns `HTTP_ERROR 504 GATEWAY_TIMEOUT` naming `upstream_source=1`;
  - order-service's p99 jumps from 80 ms to 4900 ms;
  - db-proxy (source 3) goes `HEALTHY → SATURATED → POOL_EXHAUSTED` (50/50 connections).
- **[4]** Three sections to show:
  - **DECODED EVENTS:** JSON lines with `producer_time_ns`; `"documented"` marks values that came
    from configuration (`state`, `status_name`).
  - **DOMAIN KNOWLEDGE:** three documents were retrieved because their terms (`POOL_EXHAUSTED`,
    `GATEWAY_TIMEOUT`, `REQUEST_METRIC`) occur in the evidence. They are quoted with `| ` and
    marked as data, not instructions. *"The service returning 504 is usually not the one that
    is slow."*
  - **Undocumented terms:** listed explicitly; the LLM is told not to explain them.
- **[5]** The cited cause is on a **different source** (3) from the failing one. Each `✓` means
  the citation was found in the evidence.
- **[6]** `ACCEPTED`.

## 2. SC1: drones (2 min). The original problem, including the opaque-bytes gap.

```bash
python demo/run_demo.py SC1
```

Point out:

- **[2]**
  - Events are grouped by drone, with no cross-drone timeline.
  - In the file, 474's `AVOIDANCE` *arrived* before 298's `LIDAR_TIMEOUT`. Arrival order means
    nothing, and nothing is reordered.
  - The `DIAGNOSTIC` row is `PARTIALLY_DECODED`: status and temperature decoded, 8 vendor bytes
    not.
- **[3]** `OPAQUE_BYTES: 8 payload bytes ... were not decoded because their structure is not
  configured`.
- **[4]**
  - The 8 bytes appear **nowhere** in the context, in any encoding (test V01 checks hex,
    base64 and byte lists). Only the gap appears, under DATA QUALITY.
  - `LIDAR_TIMEOUT` pulled in the LiDAR-timeout document; `POSITION` and `IN_FORMATION` are
    listed as undocumented.
  - A `Clock caveat:` line is present because there are three sources.
- **[5]** The uncertainty states that clocks are not synchronised. `data gaps` quotes the
  diagnostic's event id, which is how the validator checks that the gap was reported.

## 3. SC5: clock skew (1.5 min). The system refuses to over-claim causality.

```bash
python demo/run_demo.py SC5 --short
```

Point out:

- **[2]** AGV-7's `REPLAN` (PATH_BLOCKED, aisle 14) is stamped **11:30:09.500**, *before*
  AGV-12's `BATTERY_CRITICAL` (11:30:10.000) and its `STOPPED` in aisle 14.
  - Taken at face value, the replan happened before the blockage.
  - In truth AGV-7's clock runs 900 ms slow. That ground truth is in `scenarios/catalogue.py`
    and is never given to the pipeline.
- The producer stamps are **kept as evidence, not corrected** (hard rule 5).
- **[5]** Confidence is `low`. The link rests on the shared aisle 14, *not* on timestamps, and
  the uncertainty says the timestamps can neither support nor rule out the causal link.
- If an LLM left out the clock statement while citing several sources, validator rule 4 would
  add it and flag the answer (tests Y05 and SC5).

## 4. SC6 and SC7: negative controls (1.5 min). No invented failures.

```bash
python demo/run_demo.py SC6 SC7 --short
```

Point out:

- **SC6:**
  - **[3]** No gaps.
  - **[5]** `No failure evidence found`, `likely cause: (none asserted)`, confidence `low`, no
    contributing events.
- **SC7:**
  - **[2]** Every row is `? 0x5F0` / `? 0x7DF` with `UNKNOWN_EVENT_TYPE (nothing decoded)`.
    The system does not guess what an unconfigured CAN frame means.
  - **[4]** Shows `No event in this window could be decoded.`
  - **[5]** No cause is asserted; each unknown event is listed as a data gap.
- An answer that *guessed* ("frame 0x5F0 shows the wheel-speed sensor failed") is
  **rejected** by validator rule 5 (test SC7).
- *Be candid:* for SC6, the validator cannot prove that a cause built from normal events is
  wrong. That is the job of the prompt and of live evaluation (VERIFICATION_REPORT I3).

## 5. Y02: a hallucinated citation caught (1 min). The validator in action.

```bash
python demo/run_demo.py Y02
```

Point out:

- The header shows the fabricated citation: a `LIDAR_STATUS` from **drone 901** that was never
  retrieved.
- **[5]** That line is marked `✗ NOT IN EVIDENCE`; the three real citations keep their `✓`.
- **[6]** `REJECTED`, with
  `rule 1 CITATION_NOT_IN_EVIDENCE (not correctable): contributing event LIDAR_STATUS from source 901 ... is not in the evidence`.
- Corrections versus rejections:
  - an omitted gap or a missing clock caveat is *corrected* (`ACCEPTED_WITH_CORRECTIONS`);
  - a fabricated citation, an invalid confidence, or interpreting unknown data is *rejected*.

## 6. G01: domain swap (1.5 min). The same code with a different YAML pack.

```bash
python demo/run_demo.py G01
ls schema_packs/ schema_packs/d2_microservices schema_packs/d2_microservices/docs
cat schema_packs/d2_microservices/db_pool_status.yaml
grep -rniE '(^|[^a-z])(drone|lidar|uav|formation|swarm)' fss_py/ ; echo "exit=$?"   # no hits: exit=1
```

Point out:

- Five packs are discovered by listing the directory (no registration code). D4 (vehicle CAN)
  is **big-endian**; the rest are little-endian.
- All eight scenarios run through the same `run_scenario → investigate` path and are
  `ACCEPTED`.
- A pack is only YAML (byte layout, enum maps) plus Markdown (domain documents). Adding a
  domain means adding a directory (test G04 does exactly that).
- The core package contains no domain vocabulary (test G02).

## Optional: a real LLM

```bash
pip install -r requirements-app.txt
export FSS_LLM_API_KEY=...            # never commit it
python demo/run_demo.py SC1 --live    #  output saved to demo/outputs/SC1.live.json
```

The live client constrains reply to the `FailureSynthesis` JSON schema. The same
validator then checks it. Live runs cannot request extra context (VERIFICATION_REPORT I5).

## Appendix: the raw evidence from the CLI

```bash
python -m fss_py --fixture fixtures/golden/scenario_298_474.bin \
    --start 2026-10-08T10:07:00Z --end 2026-10-08T10:07:10Z \
    --query "Why did source 474 change state?" --output both
```
