# Real-world significance of the Failure Synthesis System (FSS)

**Audience:** professors reviewing the project, and interviews for SRE, observability and
platform roles.
**Scope:** why crash-tolerant evidence capture, bounded cross-source reconstruction,
deterministic binary decoding and LLM explanation with explicit unknowns matter outside the
lab. India-specific sources come first wherever they exist.

## How to read this document

- **Access dates.** Every source was accessed on **2026-10-09** unless stated otherwise.
  Sources are numbered `[S#]`; the full list is in [§7](#7-sources).
- **Verification level.** Each claim is tagged by how it was checked:
  - **(primary)**: read in the source itself (official postmortem, regulator text, filing,
    dataset page).
  - **(secondary)**: reported by a news outlet, law firm or vendor, because the primary text
    was paywalled, blocked (HTTP 403) or not located. Treat these as reported, not confirmed.
  - **(excerpt)**: seen only in search-result excerpts of the cited page.
- **Unverified items** are marked **unverified**, or left out.
- **Quotes** are short, under 15 words. Everything else is paraphrase.
- **Internal facts** about FSS (test counts, throughput, crash-harness results) come from this
  repository (`VERIFICATION_REPORT.md`, `RESULTS.md`), not from the web. They are labelled
  *(project)*.

---

## 1. The problem is real

Each incident below is tagged with the property it shows:

- **(a)** The root cause sat in a different component, or a different organisation, from the
  visible failure.
- **(b)** Logs, telemetry or recorded evidence were lost, incomplete, overwritten or
  unreachable when they were needed.

### Summary

| # | Incident | Visible failure | Where the cause was | (a) | (b) | India |
|---|---|---|---|:-:|:-:|:-:|
| 1 | AWS us-east-1, Oct 2025 | EC2 launches, load balancers, Lambda, IAM sign-in… | DynamoDB's DNS automation | ✓ | | |
| 2 | AWS S3, Feb 2017 | S3 and dependent services; status page frozen | A mistyped capacity-removal command | ✓ | ✓ | |
| 3 | AWS Kinesis, Nov 2020 | CloudWatch, Cognito, Lambda errors | Kinesis front-end thread limit | ✓ | ✓ | |
| 4 | Meta (Facebook), Oct 2021 | DNS unreachable worldwide | A backbone maintenance command | ✓ | ✓ | |
| 5 | Roblox, Oct 2021 (73 h) | Platform down | Consul streaming + BoltDB | | ✓ | |
| 6 | Cloudflare, Nov 2025 | HTTP 5xx from the core proxy | A database permission change | ✓ | ✓ (misleading signal) | |
| 7 | Google Cloud, Jun 2025 | 503s across many products | A policy record hitting an unguarded null pointer | ✓ | ✓ | |
| 8 | CrowdStrike Channel File 291, Jul 2024 | Windows crashes; airline check-in in India went manual | A third-party sensor content file | ✓ | | ✓ |
| 9 | NPCI UPI, Apr 2025 | UPI payments declined nationwide | Bank-side status-check API floods (reported) | ✓ | | ✓ |
| 10 | Alaska Airlines 1282, Jan 2024 | Door plug blew out in flight | Manufacturing process; **CVR audio overwritten** | | ✓ | |
| 11 | Air India AI171, Jun 2025 | Crash after take-off | Under investigation; **aft recorder unreadable** | | ✓ | ✓ |
| 12 | NTSB DCA17IA202, Sep 2017 | Army Black Hawk struck by a drone | A drone flown beyond line of sight; **drone logs were the evidence** | | ✓ (drone logs) | |

### 1.1 AWS us-east-1: DynamoDB DNS race condition (19–20 Oct 2025) [S1] (primary)

- **What happened:**
  - A latent race condition in DynamoDB's automated DNS management left the regional
    endpoint's DNS record empty.
  - Customers and internal AWS services could not resolve DynamoDB.
  - The disruption ran from 11:48 PM PDT on 19 Oct to 2:20 PM PDT on 20 Oct.
- **Where the cause was:** in DNS automation. Many of the visible failures were elsewhere:
  - EC2 instance launches failed until 1:50 PM;
  - Network Load Balancer connection errors ran from 5:30 AM to 2:09 PM;
  - Lambda, ECS, EKS, Fargate, Connect, STS, IAM console sign-in and Redshift were affected.
- **How evidence mattered:**
  - Engineers tied the outage to the DynamoDB DNS state by 12:38 AM.
  - The load-balancer health-check problem was detected separately by monitoring at 6:52 AM.
  - Diagnosis meant correlating signals from several services against one upstream cause.
- **FSS link:** the visible failure isn't the cause. Retrieval with `source=ALL` over a bounded
  window is the design response (FSS scenario SC2).

### 1.2 AWS S3 us-east-1 (28 Feb 2017) [S2] (primary)

- **What happened:**
  - While debugging billing, an operator ran a playbook command with one wrong input.
  - It removed many more servers than intended, including those behind S3's index and
    placement subsystems, which then needed full restarts.
- **Where the cause was:** a mistyped command, far from the visible failures. S3 itself was
  down, and so were dependants: EC2 launches, EBS restores from snapshots, and Lambda.
- **How evidence mattered:**
  - AWS could not update per-service status on its Service Health Dashboard until 11:37 AM PST.
  - The dashboard's admin console **depended on S3**.
  - Updates went out via Twitter and a banner instead.
- **FSS link:** the evidence and reporting path must not depend on the system that failed. FSS
  keeps evidence in an independent store with its own recovery.

### 1.3 AWS Kinesis us-east-1 (25 Nov 2020) [S3] (primary)

- **What happened:** a small capacity addition pushed the Kinesis front-end fleet past an OS
  thread limit, and a full fleet restart was needed.
- **Where the cause was:** in Kinesis. The symptoms appeared elsewhere:
  - CloudWatch `PutLogEvents` and `PutMetricData` errors;
  - Cognito authentication failures;
  - Lambda errors.
- **How evidence mattered:**
  - CloudWatch alarms went to `INSUFFICIENT_DATA` and **metric gaps** appeared, so telemetry
    was missing exactly when it was needed.
  - The status-posting tool depended on Cognito, which was itself impaired.
- **FSS link:** gaps must be reported as gaps, not silently absent. This is FSS's
  `RETRIEVAL_TRUNCATED` and data-gap reporting (SC8, Y03).

### 1.4 Meta / Facebook (4 Oct 2021) [S4] (primary)

- **What happened:**
  - A backbone capacity-assessment command disconnected all backbone links, and a bug in the
    audit tool failed to stop it.
  - DNS sites, unable to reach the data centres, withdrew their BGP routes.
- **Where the cause was:** in network maintenance. The visible failure was DNS: the world
  could not find Facebook's servers.
- **How evidence mattered:**
  - Internal diagnostic tools broke, and *"our primary and out-of-band network access was
    down"*.
  - Engineers had to go on-site.
- **FSS link:** recovery tooling and evidence must survive the failure they explain.

### 1.5 Roblox (28–31 Oct 2021, 73 hours) [S5] (primary)

- **What happened:** two Consul problems combined into a 73-hour outage:
  - contention from a newly enabled streaming feature;
  - a BoltDB freelist that grew to about 7.8 MB and was rewritten on every append.
- **How evidence mattered:**
  - Roblox's telemetry had a circular dependency on Consul, so the team *"lacked the telemetry
    data"* needed to diagnose it.
  - Roblox afterwards removed the dependency.
- **FSS link:** this is the clearest public case for an evidence layer that is crash-tolerant
  and independent of what it observes.

### 1.6 Cloudflare (18 Nov 2025) [S6] (primary)

- **What happened:**
  - A database access change made a ClickHouse query return duplicate rows.
  - That roughly doubled the Bot Management feature file.
  - The proxy's 200-feature limit was exceeded and it panicked, returning HTTP 5xx.
  - The incident ran from 11:20 to 17:06 UTC.
- **Where the cause was:** a permission change in a data pipeline. The visible failure was the
  core proxy.
- **How evidence mattered:**
  - Engineers *"initially wrongly suspected"* a hyper-scale DDoS.
  - One reason: the status page, hosted off-Cloudflare, went down by coincidence at the same
    time.
- **FSS link:** correlated timing across sources is not causation. FSS states clock and
  causality uncertainty explicitly (SC5, validator rule 4).

### 1.7 Google Cloud (12 Jun 2025) [S7] (primary)

- **What happened:**
  - A policy change with blank fields replicated globally within seconds.
  - Service Control code added on 29 May dereferenced it with no error handling and no
    feature flag, and crash-looped worldwide.
- **Visible failure:** 503s across many products, including Cloud Run, BigQuery, Cloud
  Storage, Compute Engine, IAM, **Cloud Logging and Cloud Monitoring**.
- **How evidence mattered:**
  - The first public report came about an hour in, because the Cloud Service Health
    infrastructure was itself *"down due to this outage"*.
  - Customers whose monitoring ran on Google Cloud lost their signal too.
- **FSS link:** unvalidated input reaching code that assumes a field exists is the bug class
  FSS's decoder guards against with load-time schema validation and bounds checks
  (S01–S11, P05, P07).

### 1.8 CrowdStrike Channel File 291 (19 Jul 2024), with India impact

- **What happened** [S8] (excerpt):
  - A new IPC Template Type defined 21 input fields, but the integration code supplied 20.
  - Evaluating the 21st field caused an out-of-bounds memory read and Windows crashed.
  - Microsoft estimated **8.5 million Windows devices**, under 1% of all Windows machines
    [S9] (primary).
- **Where the cause was:** a content update to a third-party endpoint-security sensor. The
  visible failures were at airlines, banks and hospitals.
- **India** [S10, S11] (secondary):
  - CERT-In issued critical advisory CIAD-2024-0035.
  - IndiGo, SpiceJet and Akasa moved to manual check-in and boarding.
- **FSS link:**
  - A field count that doesn't match the input is exactly what FSS's decoder handles
    deterministically: it bounds-checks before every read and returns `MALFORMED_PAYLOAD`
    instead of reading past the end (P05, B02).
  - It never crashes on a payload that is too short (B01).

### 1.9 NPCI UPI outage (12 Apr 2025), India [S12, S13] (secondary)

- **What happened** (as reported from NPCI's root-cause analysis):
  - Payment-service-provider (PSP) banks flooded the system with "Check Transaction Status"
    API calls, including for older transactions, without waiting for replies.
  - The architecture had no status-check limiter; the three-attempt, 90-second rule was left
    to banks.
  - The UPI success rate reportedly fell to about 50% for nearly two hours.
- **Where the cause was:** in client behaviour at other organisations. The visible failure was
  in UPI itself.
- **FSS link:** cross-organisation, cross-source evidence is needed to separate where the
  failure appeared from where it originated.
- **Note:** NPCI's own statement and RCA were not located; these details are reported by news
  outlets.

### 1.10 Alaska Airlines 1282 (5 Jan 2024): evidence overwritten [S14, S15] (primary/excerpt)

- **What happened:** a mid-exit door plug separated in flight. The NTSB's probable cause
  points to Boeing's training, guidance and oversight of a parts-removal process [S14]
  (excerpt).
- **How evidence mattered:**
  - The cockpit voice recorder was downloaded, but the accident-flight audio had been
    overwritten. Its circuit breaker was not pulled in time, and the unit kept only a rolling
    2 hours.
  - NTSB says at least **14 investigations since 2018** were hampered by overwritten CVR data
    [S15] (primary).
  - The FAA's final rule (published 2 Feb 2026) raises CVR duration for newly built aircraft
    from 2 to 25 hours. The old recorders overwrite the oldest data to keep a rolling 2-hour
    recording [S16] (primary).
- **FSS link:** retention and recoverability are first-class requirements, not tuning
  parameters.

### 1.11 Air India AI171 (12 Jun 2025), India [S17] (primary text, unofficial copy), [S18]

- **What happened:** a Boeing 787-8 crashed shortly after take-off from Ahmedabad.
- **Recorders:** the aircraft carried two Enhanced Airborne Flight Recorders (EAFRs).
  - **Forward EAFR:** has an independent power supply (RIPS). AAIB India downloaded it using a
    "golden chassis" and cables sourced from the NTSB: about **49 hours of flight data
    covering 6 flights**, plus **2 hours of audio**.
  - **Aft EAFR:** *"could not be downloaded through conventional means"*; its memory was
    extensively damaged.
- **How evidence mattered:**
  - At the wreck, the thrust levers were found near idle.
  - The recorder data showed they stayed at take-off thrust until impact.
  - The recorded evidence overrode the post-crash physical state.
- **Status:** the final report is still pending. Recent reporting says a draft was due around
  October 2026 (secondary; not verified).
- **FSS link:** this mirrors FSS's design choices:
  - redundant, independently powered recording is the aviation answer to evidence loss;
  - timestamps and values come from the recorder, not from inference.

### 1.12 NTSB DCA17IA202: drone strikes an Army Black Hawk (21 Sep 2017) [S19] (secondary), [S20]

- **What happened:**
  - A DJI Phantom 4 collided with a UH-60M at about 300 ft near Hoffman Island, New York,
    inside a temporary flight restriction.
  - **Probable cause:** the drone pilot's failure to see and avoid, due to intentional flight
    beyond visual line of sight.
- **How evidence mattered:**
  - The operator's drone flight logs showed an earlier flight above 400 ft.
  - At the collision, the operator was about 2.5 miles away.
  - So the drone's own logs established the causal behaviour.
  - A "9-second telemetry gap" appears in search excerpts of the NTSB report: **unverified**
    (the NTSB PDF returned HTTP 403 to our tools).
- **FSS link:** this is FSS's running example made real. Drone logs are evidence, and an
  investigation spans several aircraft.

---

## 2. Real data we can use

**Legend for the "Cross-component?" column:**

- **Yes**: the dataset labels a root-cause location inside a multi-component system, so the
  cause can differ from the component where symptoms show.
- **Partial**: a multi-component system, but the symptom and the cause are not labelled as a
  pair.
- **No**: a single component, or anomaly labels only.

| Dataset / benchmark | Domain | Size (as stated by source) | Labels | Licence | Format | Link | FSS test it could replace or strengthen | Cross-component? |
|---|---|---|---|---|---|---|---|---|
| **RCAEval** (WWW 2025 companion) [S23] | Microservices: Online Boutique, Sock Shop, Train Ticket | **735 failure cases**: RE1 375 (metrics), RE2 270 (metrics + logs; traces for 2 systems), RE3 90 (code-level faults); 11 fault types. About 3.4 GB Parquet on Hugging Face; Zenodo zips about 5.2 GB, expanding to about 38 GB | Root-cause **service and indicator** per case | MIT (benchmark code and data) | Parquet / CSV | github.com/phamquiluan/RCAEval | Replace synthetic **SC2**; add a real-data **G01**; score the live synthesis (**Y08**) against the labelled root-cause service | **Partial / Yes**: the cause service is labelled inside a multi-service system |
| **Nezha** (FSE 2023) [S24] | Microservices: Online Boutique, Train Ticket | Fault-suffering days per system; the repo's code reports 56 (OB) and 45 (TT) faults (**unverified as a dataset count**) | Root-cause labels **inside services** (`root_cause_*.json`) | MIT | Logs, metrics, traces | github.com/IntelligentDDS/Nezha | Strengthen **V**/**K**: code-region labels test "decoded vs unknown" granularity | **Partial** |
| **AIOps Challenge 2020** (Tsinghua NetMan) [S25] | Microservice system in a staging environment | Stage-1 data only | A failure CSV with **time, fault type and fault location** | Non-commercial research or teaching (README) | Business metrics, platform metrics, traces (span/parent IDs) | github.com/NetManAIOps/AIOps-Challenge-2020-Data | **SC2/SC8-style** windows with real traces; **R05** with real fan-out | **Partial** (fault location labelled; propagation visible in traces) |
| **LEMMA-RCA** (CIKM 2026) [S26] | IT **and OT**: microservices, water distribution, water treatment | "Hundreds of system entities"; size not stated | Multi-domain RCA tasks (label format **unverified**) | Dataset licence not stated on arXiv | Multi-modal | arxiv.org/abs/2406.05375 (data at lemmarca.info) | A real-data analogue of **G01** across IT and industrial domains (D2, D3) | **Partial** (unverified detail) |
| **Loghub** (ISSRE 2023) [S21, S22] | System logs: HDFS, BGL, Thunderbird and 16 others | HDFS_v1 11,175,629 lines (1.47 GiB, labelled); BGL 4,747,963 lines (708.76 MiB, labelled); Thunderbird 211,212,192 lines (29.60 GiB, labelled) | Anomaly labels (per block or line), **not** root-cause chains | Custom: free for research or academic work, cite the paper | Text logs | github.com/logpai/loghub | **B04** throughput on real volumes via a text-to-envelope adapter; **K** term coverage | **No** |
| **OpenTelemetry Demo** (Astronomy Shop) [S28, S29] | Microservices web shop | Generator, not a dataset | **Ground truth = the injected flag.** 18 flagd flags, e.g. `paymentFailure`, `paymentUnreachable`, `kafkaQueueProblems` (checkout + fraud detection), `productCatalogFailure`, `adHighCpu`, `emailMemoryLeak` | Apache-2.0 | OTLP logs, metrics, traces | opentelemetry.io/docs/demo/feature-flags | Live **SC1–SC5-style** runs with a known injected cause; a real Java↔Python **I1** smoke test | **Yes, by construction** (e.g. the payment fault surfaces at checkout) |
| **TrainTicket** [S27] | Microservices: 41 services, Java/Node/Python/Go | Benchmark system | Bring your own fault injection | Apache-2.0 | n/a | github.com/FudanSELab/train-ticket | Generate **SC2-style** cross-service failures at scale | **Yes, by construction** |
| **RflyMAD** (IJRR 2025) [S31] | Multicopter UAV | 5,629 cases (2,566 SIL, 2,566 HIL, 497 real flights); 11 fault types; about 114 GB | Fault type, parameters, injection time | **Not found** | **ULog (binary)**, telemetry, ROS bags | arxiv.org/abs/2311.11340 | **D1 decoder realism** with real binary ULog payloads; **P**/**B01**/**B02** on real message layouts | **No** (single vehicle) |
| **ALFA** (IJRR 2021) [S30] | Fixed-wing UAV | 47 autonomous flights: 23 engine failures, 24 with seven other control-surface faults; 66 min normal and 13 min post-fault | Ground-truth fault time and type | **Not verified** | ROS bags / CSV (**unverified**) | doi.org/10.1184/R1/12707963 | **ST/E** on real telemetry; **K** docs for real fault labels | **No** |
| **PX4 Flight Review logs** [S32, S33] | PX4 drones (many airframes) | Large public collection (size **unverified**) | None (no fault labels) | Logs described as CC-BY in PX4 docs; tool is BSD-3-Clause | **ULog (binary)**; bulk via `download_logs.py` | docs.px4.io (statistical analysis page) | **B01/B02** fuzzing with real message shapes; the P2 real-data replayer | **No** |
| **HCRL Car-Hacking** [S34, S35] | Vehicle CAN bus | Normal set plus 4 attack sets (DoS, fuzzy, gear spoofing, RPM spoofing) | Each injected frame labelled (attacks, not root causes) | **Not verified** | CAN ID + 8 data bytes | service.tib.eu (car-hacking-dataset) | **D4**: real CAN frames as `EventRecord(event_type = CAN ID, payload = 8 bytes)` for **P**/**B** tests. Caveat: the car was reportedly not driven during attacks [S35] | **No** |
| **danluu/post-mortems** [S36] | Public postmortems across the industry | About 200+ curated links | Categories (config errors, hardware/power, time, database …) | **No licence file** (GitHub API) | Markdown links to prose | github.com/danluu/post-mortems | Qualitative evaluation of **synthesis wording** and validator rules; a corpus for **K** documents | Text only |

**The evidence gap FSS fills synthetically.**

- No dataset above labels a **cause → effect pair across independent producers** (for example
  "the timeout on 298 caused the avoidance on 474") together with **producer clock skew**.
- Our search found **no public multi-UAV dataset** with labelled cross-agent failure chains
  [S37] (search of 2026-10-09). The closest are a single-vehicle multi-fault dataset and a
  drone-swarm *security* dataset.
- This is why SC1–SC5 encode both the cause and the effect, plus ground-truth clock offsets
  (SC5), synthetically.

**The best dataset to adopt next is RCAEval RE2.** It has:

- multi-source telemetry (metrics + logs, with traces for two systems);
- 270 cases with a labelled root-cause service;
- an MIT licence and Parquet download.

It turns SC2 from a story into a measured accuracy figure: FSS retrieves with `ALL`, and the
synthesis must name the labelled service. Pair it with the **OpenTelemetry Demo** to run the
same scenarios live through a real retriever.

---

## 3. Regulation and compliance

The implication column maps each requirement to an FSS property:

- **Dur**: durability and crash recovery
- **Ret**: retention
- **Tamp**: tamper-evidence
- **Time**: time and clock handling
- **Expl**: explainability and audit

Where FSS falls short, the column says so.

### India (first)

| Instrument | Requirement (paraphrased) | Verification | Implication for FSS |
|---|---|---|---|
| **CERT-In Directions** No. 20(3)/2022-CERT-In, 28 Apr 2022, under s.70B(6) of the IT Act [S38] | **(i)** Synchronise all ICT system clocks to NIC or NPL NTP servers, or to a traceable source that does not deviate from them. **(ii)** Report listed cyber incidents to CERT-In **within 6 hours** of noticing them. **(iv)** Enable logs of **all ICT systems** and keep them securely for a **rolling 180 days within Indian jurisdiction**; provide them with incident reports or on order. **(v)** Data-centre, VPS, cloud and VPN providers keep subscriber records for **5 years**. Effective 60 days after issue. | primary (PDF text) | **Time:** FSS keeps producer timestamps verbatim and refuses to infer cross-source order. Next step: record receive time and the clock source per producer (contract v1). **Ret:** the Java store needs a 180-day retention and compaction policy (not built). **Expl:** a 6-hour reporting window rewards fast, bounded reconstruction. |
| **DPDP Rules, 2025** (G.S.R. 846(E), notified Nov 2025) [S39, S40] | Rule 6: reasonable security safeguards, including **logging and monitoring** of access to personal data. Logs kept **at least 1 year** for breach detection, unless other law requires longer. Most rules, Rule 6 included, take effect **18 months after publication** (around May 2027). | secondary (the MeitY PDF returned 403) | **Ret:** a one-year floor. **Expl/minimisation:** FSS evidence never carries raw payload bytes to the LLM, which helps. The store itself would hold personal data and needs access control (not built). |
| **SEBI CSCRF** (circular dated 20 Aug 2024) [S41] | Covered incidents reported to SEBI and CERT-In **within 6 hours**. Exchange SOPs (e.g. MCX) add an RCA at **T+30 days**. A 2-year log retention appears in draft-stage commentary: **unverified** in the final text. | secondary | **Expl:** a root-cause report within 30 days. FSS's cited, validated synthesis plus its evidence trail is the raw material for one. |
| **Drone certification (CSUAS, S.O. 347(E), 26 Jan 2022)**, per the certification body's work instructions [S42] | Clause 7.1, *firmware tamper avoidance*: the UAS should not work if firmware is changed outside authorised updates. The Flight Module should have a hardware root of trust (TPM or TEE) that **signs data generated inside the module**. Its verification key is retained to **verify the origin of the module's logs**. | primary text of Bureau Veritas India's work instructions (issued 4 Mar 2025); the gazette itself not read | **Tamp:** producers may sign their logs. FSS keeps payloads opaque until schema decoding and computes a content `event_id`, but it does **not** verify producer signatures (a gap; a natural v1 field). |

### European Union

| Instrument | Requirement (paraphrased) | Verification | Implication for FSS |
|---|---|---|---|
| **AI Act** (Reg. (EU) 2024/1689), **Art. 12** [S43] | High-risk AI systems must **automatically record events (logs) over their lifetime**, to support risk identification, post-market monitoring and operational monitoring. | primary text via an unofficial consolidated site; EUR-Lex not read | **Expl:** FSS's LLM stage is itself an AI component. Each `Investigation` (context, LLM output, validator verdict) can be serialised (`to_dict`) but is **not yet persisted**: a gap. |
| **AI Act Art. 19 and Art. 26(6)** [S44, S45] | Providers (Art. 19) and deployers (Art. 26(6)) keep automatically generated logs for a period suited to the purpose, **at least six months**, unless other law says otherwise. | as above | **Ret:** a six-month floor for investigation records. |
| **AI Act Art. 73** [S46] | Report serious incidents **no later than 15 days** after awareness; **2 days** for widespread infringements and certain serious incidents; **10 days** where a death is involved. Do **not alter the AI system** in a way that compromises later analysis before informing authorities. | as above | **Dur/Expl:** evidence must be preserved as-is. FSS never rewrites stored events, and it decodes deterministically, so re-running an investigation reproduces it (B05). |
| **NIS2** (Dir. (EU) 2022/2555), **Art. 23** [S47] | For significant incidents: early warning **within 24 hours**, incident notification **within 72 hours**, final report **within one month**, including the likely root cause. | secondary reproduction of the OJ text | **Expl:** a stated root cause, within a month, with evidence. |

### United States

| Instrument | Requirement (paraphrased) | Verification | Implication for FSS |
|---|---|---|---|
| **OMB M-21-31** (27 Aug 2021) [S48] | Event-logging maturity tiers EL0–EL3. Logs kept **12 months in active storage and 18 months in cold storage** (Table 5, per category); full packet capture 72 hours. Logs *"protected by cryptographic methods from tampering"*, with integrity checks against **log hashes**. Timestamps in ISO 8601 / RFC 3339 **with milliseconds**, against a GPS or NIST time reference. **Alerts when logging stops unexpectedly.** The original log must be replayable. | primary (PDF text) | **Tamp:** FSS's CRC-32C detects *accidental* corruption only. Meeting this needs hash chaining or signatures: an open gap. **Ret/Dur:** a 30-month total horizon. **Time:** FSS uses ns timestamps, finer than required. **Gap reporting:** "logging stopped" maps naturally to an FSS data gap for a silent source (not yet built). |
| **PCI DSS v4.0.1, Req. 10** [S49] | 10.5.1: keep audit logs **at least 12 months**, with the **latest 3 months immediately available**. 10.3: protect logs from modification. 10.6: time synchronisation from designated time servers. | secondary (the official PCI SSC document sits behind a licence click-through) | **Ret, Tamp, Time,** as above. |
| **SEC Form 8-K Item 1.05** (adopted 26 Jul 2023) [S50] | Disclose a material cybersecurity incident **within four business days** of determining it is material. | primary | **Expl:** a fast, defensible account of scope and impact. |
| **FAA 25-hour CVR rule** (91 FR 4447, 2 Feb 2026) [S16] and the **NTSB** retrofit call [S15] | CVR duration for newly built aircraft rises from 2 h to 25 h. The NTSB wants existing aircraft retrofitted too, after at least 14 investigations were hampered. | primary | **Ret/Dur:** a rolling buffer that overwrites evidence before investigators reach it is a known failure mode. |
| **FAA Remote ID** (14 CFR Part 89) [S51] | Drones broadcast identification. FAA enforcement discretion for operators ended **16 Mar 2024**. | primary (FAA newsroom) | **Identity:** `source_id` integrity matters. FSS treats `source_id` as given by the envelope, not authenticated (a gap for drone deployments). |

### International standards

| Standard | Requirement | Verification | Implication for FSS |
|---|---|---|---|
| **ISO/IEC 27001:2022** Annex A **8.15 Logging**, **8.16 Monitoring activities**, **8.17 Clock synchronisation** [S52] | Produce, store, protect and analyse logs; monitor for anomalous behaviour; synchronise clocks to approved sources. | control titles from secondary summaries; the standard is paywalled | **Time/Tamp/Ret:** the same three themes again. |
| **EUROCAE ED-112A**, MOPS for crash-protected airborne recorder systems (2013) [S53] | The minimum specification for crash-protected flight recorders (flight data, voice, image and data-link). EASA references it as an acceptable means of compliance. | primary (EUROCAE product page; the standard is paywalled) | **Dur:** the aviation template for what FSS's J1 store does in software: a survivable medium, recovery of a valid prefix, and checks on what was recorded. |

**Takeaway:** regulators across India, the EU and the US converge on four requirements:

- logs exist and are kept for a minimum period;
- logs are protected from tampering;
- clocks are synchronised;
- incidents are reported fast with a stated root cause.

FSS already meets the evidence-integrity and explanation parts, except tamper-proofing.
Retention policy, tamper-evidence (hash chains or signatures) and persisting its own AI
decision records are the clear next steps.

---

## 4. Industry demand

### 4.1 Roles that do this work

| Role | What they do that FSS mirrors | Example live postings |
|---|---|---|
| Site Reliability Engineer | On-call, incident command, postmortems, SLOs, distributed-systems failure modes | P1, P3, P5, P9 |
| Observability engineer | Logging, metrics and tracing standards; telemetry pipelines; retention and cost | P2, P4, P8 |
| Logging / telemetry platform engineer | High-throughput log ingest, routing and storage | P6 |
| Incident analysis / reliability tooling | Postmortem processes, incident review, systemic-risk analysis | P7 |
| Flight-test / vehicle reliability engineer | Flight-test data and metrics; reliability investigations on fleets of vehicles or robots | P9 (vehicles, robotics), P10 (flight test) |
| AIOps / ML engineer | Anomaly detection, AI-assisted root-cause analysis | P2 (AI/ML for anomalies); Datadog "Staff GenAI Engineer – APM" [S89] |

### 4.2 Ten live postings (at least three in India)

These were retrieved from the employers' own job boards through the public Greenhouse or Lever
APIs. "Updated" is the board's own timestamp.

| # | Company: title | Location | Updated | Skills the posting lists (paraphrased) | FSS component that demonstrates it |
|---|---|---|---|---|---|
| **P1** [S79] | **Razorpay**: Site Reliability Engineer | **Bengaluru** | 2026-10-06 | SLIs, SLOs and error budgets for payment flows; incident command and blameless postmortems; failure modes such as retry storms, cascading failures and **partial outages of banks and partners**; Go/Java/Python; metrics, tracing and structured logging (Prometheus, Grafana, OpenTelemetry, ClickHouse …) | Cross-source retrieval, where the cause is in another organisation (SC2, UPI-style); validator-checked postmortem synthesis; Python |
| **P2** [S80] | **GitLab**: Senior SRE, Monitoring and Anomaly Detection (Monetization) | **Bangalore** | 2026-09-29 | Metrics, logs and traces with Prometheus and Grafana; automated detection of **event drops** and anomalies; SLOs, runbooks, incident handling; **AI/ML to predict anomalies**; Python | Data-gap reporting (truncation, opaque bytes, unknown types); LLM synthesis with a validator |
| **P3** [S81] | **MongoDB**: Senior Site Reliability Engineer | **Gurugram** | 2026-10-08 | Metrics to detect incidents and quantify health; 24/7 on-call; operating distributed systems; Python/Go | B04 measurement on EC2; incident evidence pipeline |
| **P4** [S82] | **Databricks**: Senior Software Engineer, Observability | **Bengaluru** | 2026-09-21 | Fleet produces terabytes of logs per day; set **standards for logging, metrics, tracing**; build emit/aggregate/store tooling; **enforce retention policies**; on-call | Schema packs as logging standards; bounded retrieval; retention gap (§3) |
| **P5** [S83] | **Zeta**: Lead Site Reliability Engineer | **Hyderabad** | created 2026-07-22 | Lead incident management; drive MTTR against an incident SLA; distributed systems, **storage systems, filesystem internals** | J1 crash-recovery store (CRC framing, valid-prefix recovery) |
| **P6** [S84] | **Datadog**: Staff Software Engineer, Logs Observability Pipelines | New York | 2026-09-29 | High-throughput **log processing, routing, transformation**; distributed systems; Go/Rust/C++; Kubernetes | Envelope wire format; single-writer ingest design (J2 is planned) |
| **P7** [S85] | **Datadog**: Senior Software Engineer, Incident Insights & Readiness | Boston / New York | 2026-10-01 | Postmortem process, incident reviews, **analysing incidents for systemic risks**; distributed failure modes; Go/Python | Synthesis contract with cited events, uncertainty and data gaps |
| **P8** [S86] | **Cloudflare**: Senior Engineering Manager, Observability | Hybrid | 2026-10-02 | Observability for an **AI-driven ecosystem**; SLOs and incident response; OTLP, ClickHouse, Grafana, Elasticsearch, Kibana | LLM explanation constrained by a validator |
| **P9** [S87] | **Nuro**: Senior Software Reliability Engineer | Mountain View | 2026-10-08 | **Reliability investigations to find contributing factors**; instrumentation; production telemetry; real-world deployed systems (**vehicles, robotics, IoT**); Python/Go/C++ | Domain packs D4 (vehicle) and D5 (robots); contributing events with explicit uncertainty |
| **P10** [S88] | **Anduril**: Flight Test Engineer | Costa Mesa | 2026-10-05 | Test plans and reports; **collect metrics for flight test events** | D1 drone pack; ULog-style binary decoding |

**What recurs across these 10 postings** (our count of the extracted requirement lines):

| Requirement | Postings |
|---|---|
| On-call or incident handling | **8/10** |
| Distributed systems | **7/10** |
| Logs, metrics, traces or telemetry, named explicitly | **7/10** |
| Python | **6/10** |
| Go | **5/10** |
| SLOs/SLIs | **3/10** |
| Postmortems or contributing-factor analysis | **3/10** |
| AI/ML | **2/10** |

Postings expire; the timestamps above record when each was live.

### 4.3 Market proxies, from filings and official releases

| Proxy | Figure | Source |
|---|---|---|
| Datadog FY2025 revenue | **$3.43 billion**, +28% YoY (release of 10 Feb 2026) | [S54] (primary, read via a reprint) |
| Dynatrace FY2026 (to 31 Mar 2026) | Revenue **$2,018 million** (+19%); ARR **$2,054 million** | [S55] (primary, SEC exhibit) |
| Elastic FY2026 (to 30 Apr 2026) | Revenue **$1.739 billion** (+17%) | [S56] (primary, SEC exhibit) |
| Cisco–Splunk | Acquisition completed **18 Mar 2024**, about **$28 billion** equity value | [S57] (secondary reprint of Cisco's release) |
| IBM–Confluent (Kafka) | Completed **17 Mar 2026**; $31/share, about **$11 billion** enterprise value | [S58] (primary, IBM 10-Q) |
| Market-research proxies (**labelled proxy**) | 2025 baselines **disagree by about 3.6×**: MarketsandMarkets $10.47 B (to $22.99 B by 2031) vs Mordor Intelligence $2.9 B | [S59, S60] (secondary). Use company revenues above instead. |
| **India demand proxy:** global capability centres (GCCs) | Nasscom–Zinnov: **1,700+ GCCs and about 1.9 million employees in FY24**. A FY26 edition is reported at **2,117 GCCs and about 2.36 million employees**. | [S61] (excerpt), [S62] (secondary) |

AI-assisted root-cause analysis is now a product category: Datadog's Watchdog RCA and Bits AI
SRE, Elastic's Agent Builder RCA workflows, Grafana Sift, and Splunk ITSI [S65, S68, S71,
S72, S73]. FSS's distinguishing claim is that *the explanation is checked against the
evidence*, not just generated.

---

## 5. Existing tools and where FSS differs

| Tool | Crash-recovery guarantee (documented) | Binary payloads | Cross-source bounded retrieval | LLM / automated explanation | Explicit unknowns | Where it is **better** than FSS |
|---|---|---|---|---|---|---|
| **Elasticsearch** (ELK) | Translog fsynced and committed **per request by default**. In `async` mode, acknowledged writes since the last commit can be lost [S63]. | `binary` field takes **Base64**, not searchable by default [S64]; payloads must be parsed upstream | Time-range queries across indices; bounds are not mandatory | Elastic's AI Assistant (deprecated in 9.4) and Agent Builder RCA workflows that cite `trace.id` [S65] (excerpt) | Not a first-class concept (not evaluated) | Full-text search, horizontal scale, security, ecosystem maturity |
| **OpenSearch** | Same Lucene/translog lineage (**not separately verified**) | As Elasticsearch (not verified) | As Elasticsearch | Not evaluated | Not evaluated | As Elasticsearch, with Apache-2.0 governance |
| **Grafana Loki** | WAL **on by default**; replays acknowledged data after a crash; caveats for a corrupted WAL or full disk [S66] | Text log lines; **indexes only labels**, content stored as compressed chunks in object storage [S67] | LogQL with label selectors and time ranges | Grafana **Sift** ML investigations (Kubernetes-focused) [S68] (excerpt) | No | Very low storage cost at scale; Grafana integration |
| **Splunk** | Forwarder **indexer acknowledgment**, off by default: keeps a copy until the indexer has written it; may duplicate [S69] (excerpt) | Text events | SPL time ranges | AI Assistant for SPL (natural language ↔ SPL) [S70]; ITSI episode root-cause ordering [S71] (excerpt) | No | Enterprise SIEM, compliance reporting, maturity |
| **Datadog** | SaaS: durability is the vendor's, not customer-verifiable | Not evaluated | Unified tagging across services | **Watchdog RCA** (requires APM): *"A root cause is a state change that leads to application performance issues"*. Separates root cause, critical failure and impact [S72]. **Bits AI SRE** agent investigates alerts [S73] (excerpt). | Partly: distinguishes cause from impact | Automated correlation across a huge integration surface; production-proven |
| **Apache Kafka** | Durability through **replication** (`acks=all`, `min.insync.replicas`). Docs *"recommend you not set this and use replication for durability"* (forced fsync) [S74]. On startup, recovery checks CRC32s in the newest segment and truncates to the last valid offset [S75]. | Payload decoding is left to clients (**not separately verified**) | Offsets and time-indexed consumption; no cross-producer bounded query service | None | No | A distributed, replicated, battle-tested log; massive throughput |
| **MCAP / rosbag2** | CRCs on chunks, the data section and the summary; index at the end of the file [S76]. `mcap recover` *"reads a potentially corrupt or truncated MCAP file"* and rebuilds the indexes [S77]. | **Native binary messages with per-channel schemas** [S76]. rosbag2's default storage since ROS 2 Iron [S78]. | Time-range reads within a file; not a multi-source retrieval service | None | No | Robotics ecosystem and tooling; a richer schema/encoding registry than FSS's YAML |
| **FSS** *(project)* | J1: CRC-32C framed records, recovery to a valid per-source prefix. Team-reported harness: 60 SIGKILL runs, 0 acknowledged events lost; truncation at all 327,681 byte offsets; 0 corrupt records returned (RESULTS.md, **not re-run** in verification) | **YAML schema packs** decode binary payloads deterministically. Unknown types, opaque bytes and malformed payloads are statuses, never guesses. | **Mandatory** bounded window (≤ 1 h), `source=ALL`, `max_events` and a `truncated` flag. LLM follow-up requests are re-checked against the same contract. | LLM output must follow a `FailureSynthesis` contract; a **validator rejects fabricated citations** (Y02) and restores omitted gaps | **Yes: first-class.** Data gaps are mandatory in every synthesis | — |

**Being fair: where FSS is weaker.**

- It is single-node, with no replication and no authentication.
- There is no full-text search, and it is not production-tested.
- CRC-32C detects corruption, not tampering.
- The live LLM path has not been evaluated (Y08 skipped: no API key).
- The validator's checks are lexical.

FSS's contribution is not a better log store. It is the **combination**: a crash-recovery
guarantee, deterministic binary decoding with explicit unknowns, contract-bounded
cross-source retrieval, and an LLM explanation that is *checked against the evidence*. No
single tool above documents all of these.

---

## 6. Significance statement

### 6.1 One paragraph for the report introduction

In real outages the visible failure and its cause are often in different components, and
sometimes in different organisations:

- an AWS DNS automation fault surfaced as EC2 and load-balancer failures [S1];
- Cloudflare's 2025 outage began with a database permission change and appeared as proxy
  errors [S6];
- India's UPI disruption of April 2025 was reportedly traced to bank-side API traffic rather
  than UPI itself [S12].

The evidence needed to see this is fragile:

- Roblox could not diagnose a 73-hour outage because its telemetry depended on the failing
  system [S5];
- Alaska Airlines 1282's cockpit audio was overwritten [S14];
- one of Air India AI171's two recorders could not be read by conventional means [S17].

Regulators now require the missing pieces. India's CERT-In mandates 180-day log retention,
NIC/NPL-synchronised clocks and 6-hour incident reporting [S38]. US federal guidance demands
tamper-protected logs [S48]. The EU AI Act requires lifetime logging for high-risk AI systems
[S43].

FSS addresses this gap as a domain-agnostic evidence layer. Events are stored crash-tolerantly,
retrieved across sources in a mandatory bounded window, and decoded deterministically from
configuration. They are then explained by an LLM whose output must cite real events and state
what remains unknown.

### 6.2 Five slide bullets for the professors

1. **The cause is rarely where the failure shows.** AWS 2025, Cloudflare 2025 and NPCI UPI
   2025 all failed visibly far from the cause. FSS retrieves `ALL` sources in a bounded window
   by design.
2. **Evidence dies with the system.** Roblox's telemetry depended on Consul; AWS's status tools
   depended on S3 and Cognito; Alaska 1282's CVR was overwritten. FSS keeps evidence in an
   independent crash-recovering store.
3. **Regulation demands it, India first.** CERT-In requires 180-day logs, synchronised clocks
   and 6-hour reporting. The DPDP Rules set a one-year log floor. Drone certification expects
   signed flight-module logs.
4. **LLMs must not guess.** FSS decodes binary deterministically. Unknowns stay unknown, and a
   validator rejects hallucinated citations (Y02). That is explainability that can be audited.
5. **Real data exists to measure it.** RCAEval (735 labelled failures), the OpenTelemetry
   Demo's fault flags, and the RflyMAD/PX4 binary drone logs. FSS's synthetic SC1–SC5 fill
   the cross-producer, clock-skew gap no public dataset labels.

### 6.3 Three interview talking points

1. **Problem.**
   > "In postmortems like Roblox 2021 and AWS Kinesis 2020, the telemetry you needed depended
   > on the thing that broke, and the cause sat in a different component. I built an evidence
   > layer that survives crashes and reconstructs a bounded, cross-source window around the
   > failure."
2. **Design decision.**
   > "We made the time window mandatory and the decoding deterministic. Retrieval rejects
   > unbounded or oversized requests rather than clamping them, even when the LLM asks for more
   > context. Binary payloads are decoded only from versioned YAML schemas, so unknown event
   > types and opaque bytes become explicit data gaps instead of LLM guesses."
3. **Measured result** *(project)*.
   > "445 automated tests, including property-based fuzzing, pass on an 8-vCPU EC2 instance.
   > The decoder sustains about 96,000 events per second across five domain schemas. In the
   > storage layer's crash harness (team-reported), 60 SIGKILL runs lost zero acknowledged
   > events, and truncating the file at every one of 327,681 byte offsets never returned a
   > corrupt record. The validator rejects a fabricated citation in the demo."

---

## 7. Sources

All accessed **2026-10-09**. Verification levels are as in the [introduction](#how-to-read-this-document).

**Incidents**

1. [S1] AWS, *Summary of the Amazon DynamoDB service disruption in us-east-1* (Oct 2025): https://aws.amazon.com/message/101925/ (primary)
2. [S2] AWS, *Summary of the Amazon S3 service disruption* (Feb 2017): https://aws.amazon.com/message/41926/ (primary)
3. [S3] AWS, *Summary of the Amazon Kinesis event* (Nov 2020): https://aws.amazon.com/message/11201/ (primary)
4. [S4] Meta Engineering, *More details about the October 4 outage*: https://engineering.fb.com/2021/10/05/networking-traffic/outage-details/ (primary)
5. [S5] Roblox, *Roblox return to service 10/28–10/31 2021*: https://about.roblox.com/newsroom/2022/01/roblox-return-to-service-10-28-10-31-2021 (primary)
6. [S6] Cloudflare, *18 November 2025 outage*: https://blog.cloudflare.com/18-november-2025-outage/ (primary)
7. [S7] Google Cloud Service Health, incident report of 12 Jun 2025: https://status.cloud.google.com/incidents/ow5i3PPK96RduMcb1SsW (primary)
8. [S8] CrowdStrike, *Channel File 291 Incident Root Cause Analysis* (6 Aug 2024): https://www.crowdstrike.com/wp-content/uploads/2024/08/Channel-File-291-Incident-Root-Cause-Analysis-08.06.2024.pdf (excerpt)
9. [S9] Microsoft, *Helping our customers through the CrowdStrike outage* (20 Jul 2024): https://blogs.microsoft.com/blog/2024/07/20/helping-our-customers-through-the-crowdstrike-outage/ (excerpt)
10. [S10] CERT-In advisory CIAD-2024-0035 (copy on Vikaspedia): https://en.vikaspedia.in/viewcontent/news/outage-of-microsoft-windows-due-to-crowd-strike-agent-falcon-sensor-update?lgn=en (secondary)
11. [S11] Business Today, CERT-In advisory and MeitY response (19 Jul 2024): https://www.businesstoday.in/amp/technology/news/story/microsoft-outage-cert-issues-critical-advisory-govt-takes-cognisance-of-microsoft-outage-437818-2024-07-19. Moneylife, airline disruption: https://moneylife.in/article/microsoft-faces-global-outage-affects-airline-operations-and-windowsbased-pcs-laptops/74691.html (secondary)
12. [S12] Outlook Money, *UPI outage attributed to surge in API calls from banks, says NPCI*: https://www.outlookmoney.com/banking/upi-outage-attributed-to-surge-in-api-calls-from-banks-says-npci (secondary)
13. [S13] IANS, *NPCI directs banks to limit 'check transaction' API usage*: https://ianslive.in/npci-directs-banks-to-limit-check-transaction-api-usage-to-avoid-upi-outage--20250429145943 (secondary)
14. [S14] NTSB, DCA24MA063 Board Meeting Summary (24 Jun 2025): https://www.ntsb.gov/investigations/Documents/DCA24MA063%20Board%20Meeting%20Summary.pdf. CVR Specialist's Factual Report: https://data.ntsb.gov/Docket/Document/docBLOB?ID=17055117&FileExtension=pdf&FileName=DCA24MA063+-+CVR+-+FINAL-Rel.pdf (excerpt)
15. [S15] NTSB press release NR20240213, *Retrofit all CVR-equipped airplanes with 25-hour CVRs*: https://www.ntsb.gov/news/press-releases/Pages/NR20240213.aspx (primary)
16. [S16] Federal Register 2026-02110, *25-Hour Cockpit Voice Recorder Requirement, New Aircraft Production* (2 Feb 2026): https://www.govinfo.gov/content/pkg/FR-2026-02-02/html/2026-02110.htm (primary)
17. [S17] AAIB India, *Preliminary Report, B787-8 VT-ANB, Ahmedabad, 12 Jun 2025*. Read from an unofficial copy: https://indi.ca/content/files/2025/07/Air-India-Crash-Report.pdf. The official host is aaib.gov.in (exact URL not located). (primary text, unofficial copy)
18. [S18] UK AAIB, *AAIB update: preliminary report into Air India flight AI171* (12 Jul 2025): https://www.gov.uk/government/news/aaib-update-preliminary-report-into-air-india-flight-ai171 (primary)
19. [S19] Plane & Pilot, *NTSB issues final report on Black Hawk/drone collision* (15 Dec 2017): https://planeandpilotmag.com/ntsb-final-report-black-hawk-drone-collision/ (secondary)
20. [S20] NTSB CAROL report link for DCA17IA202, as given in search results (HTTP 403 to our tools): https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/96058/pdf (**unverified**)

**Datasets**

21. [S21] Loghub: https://github.com/logpai/loghub (primary)
22. [S22] Loghub licence: https://raw.githubusercontent.com/logpai/loghub/master/LICENSE (primary)
23. [S23] RCAEval: https://github.com/phamquiluan/RCAEval (primary)
24. [S24] Nezha: https://github.com/IntelligentDDS/Nezha (primary)
25. [S25] AIOps Challenge 2020 data: https://github.com/NetManAIOps/AIOps-Challenge-2020-Data (primary)
26. [S26] LEMMA-RCA (arXiv 2406.05375): https://arxiv.org/abs/2406.05375 (primary)
27. [S27] TrainTicket: https://github.com/FudanSELab/train-ticket (primary)
28. [S28] OpenTelemetry Demo, feature flags: https://opentelemetry.io/docs/demo/feature-flags/ (primary)
29. [S29] OpenTelemetry Demo repository (Apache-2.0, via the GitHub API): https://github.com/open-telemetry/opentelemetry-demo (primary)
30. [S30] ALFA dataset (arXiv 1907.06268; DOI 10.1184/R1/12707963): https://arxiv.org/abs/1907.06268 (excerpt)
31. [S31] RflyMAD (arXiv 2311.11340): https://arxiv.org/abs/2311.11340 (excerpt)
32. [S32] PX4 docs, statistical flight log analysis: https://docs.px4.io/main/en/dev_log/flight_log_analysis_statistical (excerpt)
33. [S33] PX4 Flight Review (BSD-3-Clause, via the GitHub API): https://github.com/PX4/flight_review (primary)
34. [S34] HCRL Car-Hacking Dataset listing (TIB): https://service.tib.eu/ldmservice/dataset/car-hacking-dataset (excerpt)
35. [S35] Verma et al., *A Comprehensive Guide to CAN IDS Data & Introduction of the ROAD Dataset*: https://arxiv.org/abs/2012.14600 (excerpt)
36. [S36] danluu/post-mortems: https://github.com/danluu/post-mortems (primary)
37. [S37] IEEE DataPort, multi-fault multirotor dataset: https://ieee-dataport.org/documents/multi-fault-dataset-multirotor-uavs-single-and-double-magnitude-faults. Drone-swarm cyber-physical dataset: https://ieee-dataport.org/documents/cyber-physical-dataset-drone-swarms-coordinated-formations (excerpt)

**Regulation**

38. [S38] CERT-In, *Directions under section 70B(6) of the IT Act*, 28 Apr 2022: https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf (primary)
39. [S39] SCC Online, *MeitY notified DPDP Rules 2025*: https://www.scconline.com/blog/post/2025/11/14/meity-notified-digital-personal-data-protection-rules-2025/. MeitY PDF (HTTP 403): https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf (secondary)
40. [S40] KPMG India, *DPDP Rules 2025 guidance*: https://assets.kpmg.com/content/dam/kpmgsites/in/pdf/2025/11/dpdp-rules-2025-guidance-to-dpdp-act-implementation.pdf (excerpt)
41. [S41] SEBI CSCRF circular page: https://www.sebi.gov.in/legal/circulars/aug-2024/cybersecurity-and-cyber-resilience-framework-cscrf-for-sebi-regulated-entities-res-_85964.html (not read). MCX SOP summary: https://www.indialaw.in/blog/civil/mcx-updates-sop-cybersecurity-incidents/. DSCI inputs: https://www.dsci.in/files/content/documents/2025/8-Inputs_on_the_SEBI-CSCRF.pdf (secondary)
42. [S42] Bureau Veritas India, *UAS – Guidelines for Certification Criteria* (work instructions, issued 4 Mar 2025; gazetted reference S.O. 347(E)): https://cdn1-www.bureauveritas.co.in/sites/g/files/zypfnx556/files/media/document/UAS%20-%20Guidelines%20for%20Certification%20Criteria.pdf (primary text of the certification body's document)
43. [S43] EU AI Act Art. 12 (consolidated text): https://artificialintelligenceact.eu/article/12/. Official: https://eur-lex.europa.eu/eli/reg/2024/1689/oj (not read)
44. [S44] EU AI Act Art. 19: https://artificialintelligenceact.eu/article/19/
45. [S45] EU AI Act Art. 26: https://artificialintelligenceact.eu/article/26/
46. [S46] EU AI Act Art. 73: https://artificialintelligenceact.eu/article/73/
47. [S47] NIS2 Directive Art. 23 (reproduction of OJ L 333, 27.12.2022): https://www.springlex.eu/en/packages/nis2/nis2-directive/article-23/. Official: https://eur-lex.europa.eu/eli/dir/2022/2555/oj (not readable by our tools) (secondary)
48. [S48] OMB M-21-31 (27 Aug 2021): https://www.whitehouse.gov/wp-content/uploads/2021/08/M-21-31-Improving-the-Federal-Governments-Investigative-and-Remediation-Capabilities-Related-to-Cybersecurity-Incidents.pdf (primary)
49. [S49] PCI DSS v4.0.1 Req. 10.5.1 summary (Cloudaware): https://ce.prod.cloudaware.com/frameworks/pci-dss-v4.0.1/10/05/01. Official library: https://www.pcisecuritystandards.org/document_library/ (not read) (secondary)
50. [S50] SEC press release 2023-139, cybersecurity disclosure rules: https://www.sec.gov/newsroom/press-releases/2023-139 (primary)
51. [S51] FAA, *FAA extends Remote ID enforcement date six months*: https://www.faa.gov/newsroom/faa-extends-remote-id-enforcement-date-six-months (excerpt)
52. [S52] ISMS.online, ISO 27002 control 8.17 clock synchronisation: https://www.isms.online/iso-27002/control-8-17-clock-synchronisation (secondary)
53. [S53] EUROCAE, *ED-112A MOPS for Crash Protected Airborne Recorder Systems*: https://www.eurocae.net/product/ed-112a-mops-for-crash-protected-airborne-recorder-systems/ (excerpt)

**Market and companies**

54. [S54] Datadog, *Fourth quarter and fiscal year 2025 results* (10 Feb 2026): https://investors.datadoghq.com/news-releases/news-release-details/datadog-announces-fourth-quarter-and-fiscal-year-2025-financial. Read via the reprint at https://www.stocktitan.net/news/DDOG/datadog-announces-fourth-quarter-and-fiscal-year-2025-financial-buqhnpplsjrr.html
55. [S55] Dynatrace FY26 Q4 earnings release (SEC exhibit, 13 May 2026): https://www.sec.gov/Archives/edgar/data/0001773383/000177338326000011/fy26q4-earningsreleaseex99.htm (primary)
56. [S56] Elastic FY26 Q4 earnings release (SEC exhibit): https://www.sec.gov/Archives/edgar/data/0001707753/000170775326000008/a26q4erex991.htm (primary)
57. [S57] Cisco release reprinted by Fierce Network: https://fierce-network.com/newswire/cisco-completes-acquisition-splunk. SiliconANGLE: https://siliconangle.com/2024/03/18/cisco-completes-28b-acquisition-splunk/ (secondary)
58. [S58] IBM Form 10-Q, quarter ended 31 Mar 2026 (Confluent acquisition): https://www.sec.gov/Archives/edgar/data/0000051143/000005114326000038/ibm-20260331.htm (excerpt)
59. [S59] MarketsandMarkets figures via a Daily Tribune press-release repost: https://www.daily-tribune.com/online_features/press_releases/observability-tools-platforms-market-projected-to-hit-22-99-billion-by-2031-at-14-1/article_5f10c274-1129-532b-a91c-a6e62b24cad3.html (secondary, labelled proxy)
60. [S60] Mordor Intelligence, observability market: https://mordorintelligence.com/industry-reports/observability-market (secondary, labelled proxy)
61. [S61] Nasscom, *India GCC Landscape Report: The 5 Year Journey*: https://nasscom.in/knowledge-center/publications/india-gcc-landscape-report-5-year-journey. ThePrint coverage: https://theprint.in/economy/indias-position-as-gcc-capital-of-the-world-nasscom-zinnov-study/2268673/ (excerpt)
62. [S62] Business Today, FY26 GCC figures (7 May 2026): https://www.businesstoday.in/amp/technology/news/story/the-big-boom-how-indias-gcc-story-hits-2030-target-4-years-early-530265-2026-05-07 (secondary)

**Tool documentation**

63. [S63] Elasticsearch translog settings: https://www.elastic.co/docs/reference/elasticsearch/index-settings/translog (primary)
64. [S64] Elasticsearch `binary` field type: https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/binary (primary)
65. [S65] Elastic, *Automate root cause analysis for an observability alert*: https://www.elastic.co/docs/explore-analyze/workflows/use-cases/observability/root-cause-analysis (excerpt)
66. [S66] Grafana Loki, write-ahead log: https://grafana.com/docs/loki/latest/operations/storage/wal/ (primary)
67. [S67] Grafana Loki overview: https://grafana.com/docs/loki/latest/get-started/overview/ (primary)
68. [S68] Grafana Cloud IRM, *Investigate with Sift*: https://grafana.com/docs/grafana-cloud/alerting-and-irm/irm/manage-incidents/investigate/ (excerpt)
69. [S69] Splunk, *Protect against loss of in-flight data* (10.0): https://help.splunk.com/en/splunk-enterprise/forward-and-process-data/forwarding-and-receiving-data/10.0/perform-advanced-configuration/protect-against-loss-of-in-flight-data (excerpt)
70. [S70] Splunk AI Assistant for SPL: https://docs.splunk.com/Documentation/AIAssistant/latest/User/AboutAIAssistant (excerpt)
71. [S71] Splunk ITSI, *Investigate episodes*: https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/detect-and-act-on-notable-events/4.21/episode-review/investigate-episodes-in-itsi (excerpt)
72. [S72] Datadog Watchdog RCA: https://docs.datadoghq.com/watchdog/rca/ (primary)
73. [S73] Help Net Security, *Datadog introduces Bits AI SRE* (3 Dec 2025): https://www.helpnetsecurity.com/2025/12/03/datadog-bits-ai-sre-agent/ (excerpt)
74. [S74] Apache Kafka topic configs (4.1), `flush.messages`: https://kafka.apache.org/41/configuration/topic-configs/ (primary)
75. [S75] Apache Kafka log implementation (3.5), recovery and CRC: https://kafka.apache.org/35/implementation/log/ (primary)
76. [S76] MCAP specification: https://mcap.dev/spec (primary)
77. [S77] MCAP CLI guide (`recover`, `doctor`): https://mcap.dev/guides/cli (primary)
78. [S78] Foxglove, *MCAP as the ROS 2 default bag format*: https://foxglove.dev/blog/mcap-as-the-ros2-default-bag-format. ROS docs: https://docs.ros.org/en/iron/p/rosbag2_storage_mcap (excerpt)

**Job postings** (live on 2026-10-09; retrieved through the public Greenhouse or Lever APIs)

79. [S79] P1 Razorpay, Site Reliability Engineer, Bengaluru: https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited/jobs/4723040005
80. [S80] P2 GitLab, Senior SRE – Monitoring and Anomaly Detection (Monetization), Bangalore: https://job-boards.greenhouse.io/gitlab/jobs/8615319002
81. [S81] P3 MongoDB, Senior Site Reliability Engineer, Gurugram: https://www.mongodb.com/careers/job/?gh_jid=8051379
82. [S82] P4 Databricks, Senior Software Engineer – Observability, Bengaluru: https://databricks.com/company/careers/open-positions/job?gh_jid=7619811002
83. [S83] P5 Zeta, Lead Site Reliability Engineer, Hyderabad: https://jobs.lever.co/zeta/803792f5-0e9c-45bc-82ce-c0a552ce0cf8
84. [S84] P6 Datadog, Staff Software Engineer – Logs Observability Pipelines, New York: https://careers.datadoghq.com/detail/7743369/?gh_jid=7743369
85. [S85] P7 Datadog, Senior Software Engineer – Incident Insights & Readiness, Boston/New York: https://careers.datadoghq.com/detail/8247566/?gh_jid=8247566
86. [S86] P8 Cloudflare, Senior Engineering Manager, Observability: https://boards.greenhouse.io/cloudflare/jobs/8185558?gh_jid=8185558
87. [S87] P9 Nuro, Senior Software Reliability Engineer, Mountain View: https://nuro.ai/careersitem?gh_jid=7875059
88. [S88] P10 Anduril, Flight Test Engineer, Costa Mesa: https://boards.greenhouse.io/andurilindustries/jobs/5093774007?gh_jid=5093774007
89. [S89] Datadog, Staff GenAI Engineer – Application Performance Monitoring (APM), New York: https://careers.datadoghq.com/detail/7974511/?gh_jid=7974511

**Internal project sources** (not web): `VERIFICATION_REPORT.md` (445 tests; B04 ≈ 96,000 events/s on an 8-vCPU EC2 instance; Y02 rejection), `RESULTS.md` (team-reported J1 crash-harness figures) and `FSS_PROJECT.md` (design).

---

## Five-line summary

1. **Strongest real-world justification:** postmortems where the evidence depended on the
   failing system and the cause was elsewhere: Roblox 2021 (telemetry lost to a Consul
   dependency) [S5], AWS 2017 and 2020 (status tools depended on S3 and Cognito) [S2, S3]. In
   India, Air India AI171's unreadable aft recorder [S17] and the UPI April 2025 cascade
   [S12].
2. **Best real dataset to adopt next:** **RCAEval RE2**: 270 multi-source failure cases with a
   labelled root-cause service, MIT-licensed, Parquet [S23]. Run it alongside the
   **OpenTelemetry Demo** fault flags for live cross-service runs [S28].
3. **Most relevant regulation:** the **CERT-In Directions of 28 Apr 2022**: logs of all ICT
   systems kept 180 days in India, clocks synchronised to NIC/NPL, incidents reported within
   6 hours [S38].
4. **Top skill employers ask for that FSS demonstrates:** investigating incidents across
   distributed components from logs, metrics and traces (on-call or incident handling in
   8/10 postings, distributed systems in 7/10, 5 of them India-based [S79–S88]). FSS shows
   cross-source evidence reconstruction with cited, validated explanations.
5. **Not verified:**
   - NPCI's own UPI RCA (news reports only);
   - SEBI CSCRF's 2-year log retention;
   - the DPDP Rules' official text (MeitY PDF blocked);
   - the NTSB drone report's 9-second telemetry gap;
   - the ALFA, RflyMAD and HCRL licences;
   - the LEMMA-RCA size and labels;
   - the PX4 log-collection size;
   - the official PCI DSS and ISO 27001 texts (paywalled).
