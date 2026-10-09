"""Streamlit front end for the FSS demo: pick a scenario, ask your own question,
see the full report with one tab per part.

    streamlit run app.py --server.address 127.0.0.1 --server.port 8501

Scenarios run in-process (scenarios.run_scenario with the typed question). Y02 and G01
are special demo runs, so they go through demo/run_demo.py.
"""
import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from fss_py.llm import LLMError, StubLLM  # noqa: E402
from fss_py.presentation import render_investigation  # noqa: E402
from scenarios import SCENARIOS, run_scenario, stub_answer_json  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")
SECTION = re.compile(r"^\[([1-8])\] ")
SPECIAL = {"Y02": "Hallucinated citation caught by the validator",
           "G01": "Domain swap: five packs, same code"}
TABS = ["1 Question", "2 Retrieval", "3 Events", "4 Data gaps",
        "5 Knowledge", "6 LLM context", "7 Synthesis", "8 Validator"]


def live_available() -> str | None:
    """None if the live LLM can be used, else the reason it cannot."""
    if not os.environ.get("FSS_LLM_API_KEY"):
        return "FSS_LLM_API_KEY is not set"
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return "anthropic is not installed (pip install -r requirements-app.txt)"
    return None


@st.cache_data(show_spinner=False)
def run_question(sid: str, question: str, live: bool, short: bool) -> str:
    """Run one scenario with the given question; return the plain-text report."""
    sc = SCENARIOS[sid]
    if live:
        from fss_py.llm import AnthropicLLM
        llm = AnthropicLLM()
    else:
        llm = StubLLM(stub_answer_json(sc))
    inv = run_scenario(dataclasses.replace(sc, query=question), llm,
                       max_context_requests=0 if live else 1)
    who = f"live, {llm.model}" if live else "stub (canned answer stored with the scenario)"
    line = "=" * 80
    head = f"{line}\n  {sid} | {sc.pack} | {sc.title}\n{line}\nProves: {sc.proves}\nLLM: {who}\n"
    return head + render_investigation(inv, source_names=sc.source_names, colour=False,
                                       show_context=not short)


@st.cache_data(show_spinner=False)
def run_special(sid: str) -> tuple[str, str, int]:
    p = subprocess.run([sys.executable, "demo/run_demo.py", sid, "--no-colour"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    return ANSI.sub("", p.stdout), ANSI.sub("", p.stderr), p.returncode


def split_reports(out: str) -> list[tuple[str, dict[int, str]]]:
    """Split output into (header, {part number: text}) per scenario report."""
    reports: list[tuple[str, dict[int, list[str]]]] = []
    header: list[str] = []
    current: dict[int, list[str]] | None = None
    part = 0
    for line in out.splitlines():
        m = SECTION.match(line)
        if m:
            n = int(m.group(1))
            if n == 1 or current is None:
                current = {}
                reports.append(("\n".join(header).strip(), current))
                header = []
            part = n
            current[part] = [line]
        elif current is not None and part == 8 and line.startswith("="):
            current, part = None, 0  # banner of the next scenario
            header = [line]
        elif current is not None:
            current[part].append(line)
        else:
            header.append(line)
    return [(h, {n: "\n".join(ls).rstrip() for n, ls in parts.items()}) for h, parts in reports]


def show_verdict(text: str) -> None:
    if "REJECTED" in text:
        st.error("Validator verdict: REJECTED")
    elif "FAILED" in text:
        st.error("Validator verdict: FAILED")
    elif "CORRECTIONS" in text:
        st.warning("Validator verdict: ACCEPTED WITH CORRECTIONS")
    elif "ACCEPTED" in text:
        st.success("Validator verdict: ACCEPTED")


def show_report(out: str) -> None:
    reports = split_reports(out)
    if not reports:
        st.code(out, language=None)
    for header, parts in reports:
        st.code(header, language=None)
        show_verdict(parts.get(8, ""))
        for tab, n in zip(st.tabs(TABS), range(1, 9)):
            with tab:
                st.code(parts.get(n, "(part not in output)"), language=None)
    with st.expander("Raw output"):
        st.code(out, language=None)


st.set_page_config(page_title="FSS demo", layout="wide")
st.title("Failure Synthesis System: demo")
st.caption("Recorded binary events -> bounded retrieval -> deterministic decoder -> "
           "evidence -> domain docs -> LLM -> output validator")

labels = {f"{sid} - {sc.title}": sid for sid, sc in SCENARIOS.items()}
labels.update({f"{sid} - {title}": sid for sid, title in SPECIAL.items()})
sid = labels[st.sidebar.selectbox("Scenario", list(labels))]
short = st.sidebar.checkbox("Hide full LLM context", value=False)

if sid in SPECIAL:
    st.sidebar.caption("Fixed demo run: no question to type.")
    if st.sidebar.button("Run", type="primary"):
        out, err, rc = run_special(sid)
        if rc != 0:
            st.error(f"run_demo.py exited with {rc}")
        if err.strip():
            st.code(err)
        show_report(out)
    else:
        st.info("Press Run in the sidebar.")
else:
    sc = SCENARIOS[sid]
    unavailable = live_available()
    mode = st.sidebar.radio("LLM", ["Stub (offline, canned answer)", "Live Claude"],
                            help=unavailable or "Uses FSS_LLM_API_KEY; each run is a paid API call.")
    live = mode == "Live Claude"
    if live and unavailable:
        st.sidebar.error(f"Live LLM not available: {unavailable}")

    with st.form("ask"):
        question = st.text_area("Your question", value=sc.query, height=80)
        st.caption(f"Data: {sc.pack}, the scenario's fixed time window. "
                   f"Default question: “{sc.query}”")
        submitted = st.form_submit_button("Investigate", type="primary",
                                          disabled=live and bool(unavailable))
    if submitted:
        question = question.strip()
        if not question:
            st.error("Type a question first.")
        else:
            if not live and question != sc.query:
                st.warning("The stub LLM replays the answer stored for the default question, so "
                           "part 7 will not answer your question. Your question still drives "
                           "parts 1, 5 and 6 (question, knowledge ranking, LLM context). "
                           "Choose Live Claude for a real answer.")
            try:
                with st.spinner("Investigating..."):
                    out = run_question(sid, question, live, short)
            except LLMError as exc:
                st.error(f"LLM call failed: {exc}")
            else:
                show_report(out)
    else:
        st.info("Type a question (or keep the default) and press Investigate.")
