"""Streamlit front end: ask "what is wrong?" over drone event fixtures.

    streamlit run streamlit_app.py

Pipeline: envelope fixtures -> MockRetriever -> decoder -> evidence -> findings.
Findings are rule-based and cite event_ids. If ANTHROPIC_API_KEY is set, Claude can
also write an explanation grounded only on the evidence JSON (optional).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from fss_py import ALL, MockRetriever, RetrievalRequestError, build_evidence, decode_all
from fss_py.contract import UNKNOWN_LABEL
from fss_py.schema import load_schema_file
from fss_py.wire import iter_envelopes

ROOT = Path(__file__).parent
GOLDEN = ROOT / "fixtures" / "golden"
SCHEMA = ROOT / "schemas" / "drone_v0.yaml"
MAX_WINDOW_NS = 3600 * 10**9  # retrieval contract: window <= 1 h
MODEL = "claude-opus-5-5"

# (event_name, field, value) -> (severity, plain-language problem). Anything not listed is normal.
RULES: dict[tuple[str, str, str], tuple[str, str]] = {
    ("LIDAR_STATUS", "status_name", "LIDAR_TIMEOUT"): ("high", "LiDAR timed out"),
    ("LIDAR_STATUS", "status_name", "SENSOR_DISCONNECTED"): ("high", "LiDAR sensor disconnected"),
    ("LIDAR_STATUS", "status_name", "INVALID_SCAN"): ("medium", "LiDAR returned an invalid scan"),
    ("DIAGNOSTIC", "status_name", "FAULT"): ("high", "Diagnostics report FAULT"),
    ("DIAGNOSTIC", "status_name", "DEGRADED"): ("medium", "Diagnostics report DEGRADED"),
    ("FORMATION_STATE", "state", "LEFT_FORMATION"): ("high", "Left formation"),
    ("FORMATION_STATE", "state", "REJOINING"): ("low", "Rejoining formation"),
}
SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡", "info": "⚪"}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}

SYSTEM_PROMPT = """You investigate failures in a drone fleet. You receive an evidence JSON
(format fss-evidence/v0) and an operator question.

Rules:
- Use only facts in the evidence. Cite every claim with its event_id in square brackets.
- Producer clocks are not synchronized across sources. Never state a cross-drone order or
  causality as fact; say it is likely or possible and explain why.
- Anything listed in data_gaps is unknown. Say so; do not guess what it contains.
- Answer the question first in 1-3 sentences, then list supporting evidence, then gaps."""


def fmt_ns(ns: int) -> str:
    dt = datetime.fromtimestamp(ns // 10**9, tz=timezone.utc)
    return f"{dt:%Y-%m-%d %H:%M:%S}.{ns % 10**9 // 10**6:03d}"


def mentioned_drones(query: str, known: set[int]) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\b\d{1,10}\b", query) if int(n) in known})


def findings_for(evidence: dict) -> list[dict]:
    out = []
    for ev in evidence["events"]:
        name, fields = ev["event_name"] or "", ev["fields"]
        base = {"source_id": ev["source_id"], "timestamp_ns": ev["timestamp_ns"],
                "event_id": ev["event_id"], "event": name or ev["event_type"]}
        for (rule_event, key, value), (sev, text) in RULES.items():
            if name == rule_event and fields.get(key) == value:
                detail = ", ".join(f"{k}={v}" for k, v in fields.items() if k != key)
                out.append({**base, "severity": sev, "problem": text, "detail": detail})
        if name == "AVOIDANCE":
            out.append({**base, "severity": "medium",
                        "problem": f"Avoidance manoeuvre ({fields.get('reason', '?')})",
                        "detail": f"min separation {fields.get('min_separation_m')} m, "
                                  f"heading change {fields.get('heading_change_deg')}°"})
        for key in ev["interpreted_fields"]:
            if fields.get(key) == UNKNOWN_LABEL:
                out.append({**base, "severity": "low",
                            "problem": f"Undocumented {key} code", "detail": str(fields)})
    ts = {ev["event_id"]: ev["timestamp_ns"] for ev in evidence["events"]}
    for gap in evidence["data_gaps"]:
        if gap["kind"] == "UNMAPPED_ENUM":
            continue  # already reported above
        out.append({"source_id": gap["source_id"], "timestamp_ns": ts.get(gap["event_id"]),
                    "event_id": gap["event_id"], "event": gap["kind"],
                    "severity": "info", "problem": "Data gap: " + gap["kind"].replace("_", " ").lower(),
                    "detail": gap["detail"]})
    return out


def summary_markdown(findings: list[dict], focus: list[int], sources: list[int]) -> str:
    if not findings:
        return "✅ **Nothing looks wrong** in this window: every status is nominal and every event decoded."
    by_src: dict[int | None, list[dict]] = {}
    for f in findings:
        by_src.setdefault(f["source_id"], []).append(f)
    order = sorted(by_src, key=lambda s: (s not in focus, s is None, s or 0))
    lines = []
    for src in order:
        items = sorted(by_src[src], key=lambda f: (f["timestamp_ns"] or 0, SEVERITY_RANK[f["severity"]]))
        worst = min(items, key=lambda f: SEVERITY_RANK[f["severity"]])["severity"]
        who = "Retrieval" if src is None else f"Drone {src}"
        lines.append(f"{SEVERITY_ICON[worst]} **{who}**" + (" *(asked about)*" if src in focus else ""))
        for f in items:
            when = f" at {fmt_ns(f['timestamp_ns'])[11:]}" if f["timestamp_ns"] else ""
            lines.append(f"  - {f['problem']}{when}: {f['detail']} `[{f['event_id']}]`")
    healthy = [s for s in sources if s not in by_src]
    if healthy:
        lines.append(f"✅ Nothing abnormal from drone(s) {', '.join(map(str, healthy))}.")
    if len([s for s in by_src if s is not None]) > 1:
        lines.append("\n⏱️ Problems appear on several drones. Their clocks are **not synchronized**, "
                     "so the order between drones (and which one caused which) is uncertain.")
    return "\n".join(lines)


def ask_claude(evidence: dict, query: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content":
                   f"Evidence:\n```json\n{json.dumps(evidence, indent=1)}\n```\n\nQuestion: {query}"}],
    )
    if response.stop_reason == "refusal":
        return "Claude declined to answer this request."
    return "".join(b.text for b in response.content if b.type == "text")


@st.cache_resource
def registry():
    return load_schema_file(SCHEMA)


def load_events(fixture_names: list[str], uploads) -> list:
    events = []
    for name in fixture_names:
        events.extend(iter_envelopes((GOLDEN / name).read_bytes()))
    for up in uploads or []:
        events.extend(iter_envelopes(up.getvalue()))
    return events


st.set_page_config(page_title="Failure Synthesis System", page_icon="🛸", layout="wide")
st.title("🛸 Failure Synthesis System")
st.caption("Ask what went wrong. Answers come from decoded drone events, and every finding cites its event_id.")

with st.sidebar:
    st.header("Data")
    fixtures = sorted(p.name for p in GOLDEN.glob("*.bin"))
    chosen = st.multiselect("Fixtures", fixtures, default=["scenario_298_474.bin"])
    uploads = st.file_uploader("…or upload envelope streams (.bin)", type=["bin"], accept_multiple_files=True)

try:
    events = load_events(chosen, uploads)
except Exception as exc:  # malformed upload
    st.error(f"Could not read envelope stream: {exc}")
    st.stop()
if not events:
    st.info("Pick at least one fixture or upload a .bin file in the sidebar.")
    st.stop()

all_sources = sorted({e.source_id for e in events})
t_min = min(e.timestamp_ns for e in events)
t_max = max(e.timestamp_ns for e in events)

with st.sidebar:
    st.header("Retrieval window")
    st.write(f"Data spans **{fmt_ns(t_min)}** → **{fmt_ns(t_max)}** UTC")
    span_s = max(1, -(-(t_max - t_min + 1) // 10**9))
    offset = st.slider("Start (seconds after first event)", 0, max(0, span_s - 1), 0)
    length = st.slider("Length (seconds, max 3600)", 1, 3600, min(3600, max(1, span_s - offset)))
    source_choice = st.selectbox("Source", ["ALL"] + [str(s) for s in all_sources])
    max_events = st.number_input("max_events", 1, 10_000, 100)
    use_claude = st.toggle("Explain with Claude", value=False,
                           disabled=not os.environ.get("ANTHROPIC_API_KEY"),
                           help="Needs ANTHROPIC_API_KEY set on the server.")

t_start = t_min + offset * 10**9
t_end = min(t_start + length * 10**9, t_start + MAX_WINDOW_NS)

query = st.chat_input("e.g. What is wrong?  ·  Why did drone 474 leave formation?")
if "history" not in st.session_state:
    st.session_state.history = []
if query:
    st.session_state.history.append(query)
if not st.session_state.history:
    st.markdown("Type a question below, for example **“What is wrong?”** "
                "or **“Why did drone 474 leave formation?”**")
    st.stop()

query = st.session_state.history[-1]
source = ALL if source_choice == "ALL" else int(source_choice)
try:
    result = MockRetriever(events).retrieve(source, t_start, t_end, max_events=int(max_events))
except RetrievalRequestError as exc:
    st.error(f"Retrieval rejected: {exc}")
    st.stop()
decoded = decode_all(result.events, registry())
evidence = build_evidence(decoded, query=query, retrieval=result)
findings = findings_for(evidence)
focus = mentioned_drones(query, set(all_sources))

with st.chat_message("user"):
    st.write(query)
with st.chat_message("assistant"):
    n_src = len(evidence["sources"])
    st.markdown(f"Looked at **{len(decoded)} events** from **{n_src} drone(s)** "
                f"between {fmt_ns(t_start)[11:]} and {fmt_ns(t_end)[11:]} UTC"
                + (" — ⚠️ *truncated, raise max_events or narrow the window*" if result.truncated else "")
                + ".")
    st.markdown(summary_markdown(findings, focus, evidence["sources"]))
    if use_claude:
        with st.spinner("Asking Claude…"):
            try:
                st.markdown("---\n**Claude's explanation**\n\n" + ask_claude(evidence, query))
            except Exception as exc:
                st.error(f"Claude call failed: {exc}")

tab_tl, tab_find, tab_json = st.tabs(["Timeline per drone", "Findings table", "Evidence JSON"])
with tab_tl:
    st.caption(evidence["ordering"])
    for src in evidence["sources"]:
        rows = [{"time (UTC)": fmt_ns(e["timestamp_ns"])[11:], "event": e["event_name"] or e["event_type"],
                 "status": e["decode_status"],
                 "fields": ", ".join(f"{k}={v}" for k, v in e["fields"].items()),
                 "unknown bytes": e.get("unknown_bytes", 0), "event_id": e["event_id"]}
                for e in evidence["events"] if e["source_id"] == src]
        st.subheader(f"Drone {src}" + ("  ⭐" if src in focus else ""))
        st.dataframe(rows, hide_index=True, width="stretch")
with tab_find:
    st.dataframe([{**f, "severity": SEVERITY_ICON[f["severity"]] + " " + f["severity"],
                   "timestamp_ns": fmt_ns(f["timestamp_ns"]) if f["timestamp_ns"] else ""}
                  for f in sorted(findings, key=lambda f: SEVERITY_RANK[f["severity"]])],
                 hide_index=True, width="stretch")
with tab_json:
    st.download_button("Download evidence.json", json.dumps(evidence, indent=2), "evidence.json")
    st.json(evidence)
