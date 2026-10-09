"""Streamlit front end for demo/run_demo.py: one tab per report part.

    streamlit run app.py --server.address 127.0.0.1 --server.port 8501
"""
import re
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
ANSI = re.compile(r"\x1b\[[0-9;]*m")
SECTION = re.compile(r"^\[([1-8])\] ")
SCENARIOS = {
    "SC2 - microservices (failing service is not the cause)": "SC2",
    "SC1 - drones (opaque-bytes gap)": "SC1",
    "SC5 - clock skew (no over-claimed causality)": "SC5",
    "SC6 - normal events (no invented failure)": "SC6",
    "SC7 - unknown events (nothing guessed)": "SC7",
    "Y02 - hallucinated citation caught": "Y02",
    "G01 - domain swap (same code, 5 YAML packs)": "G01",
}
TABS = ["1 Question", "2 Retrieval", "3 Events", "4 Data gaps",
        "5 Knowledge", "6 LLM context", "7 Synthesis", "8 Validator"]


@st.cache_data(show_spinner=False)
def run_demo(sid: str, short: bool) -> tuple[str, str, int]:
    cmd = [sys.executable, "demo/run_demo.py", sid] + (["--short"] if short else [])
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
    return ANSI.sub("", p.stdout), ANSI.sub("", p.stderr), p.returncode


def split_reports(out: str) -> list[tuple[str, dict[int, str]]]:
    """Split output into (header, {part number: text}) per scenario report."""
    reports: list[tuple[str, dict[int, str]]] = []
    header: list[str] = []
    current: dict[int, list[str]] | None = None
    part = 0
    for line in out.splitlines():
        m = SECTION.match(line)
        if m:
            n = int(m.group(1))
            if n == 1 or current is None:
                current = {}
                reports.append(("\n".join(header).strip(), current))  # type: ignore[arg-type]
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
    return [(h, {n: "\n".join(ls).rstrip() for n, ls in parts.items()})  # type: ignore[union-attr]
            for h, parts in reports]


def show_verdict(text: str) -> None:
    if "REJECTED" in text or "FAILED" in text:
        st.error("Validator verdict: REJECTED")
    elif "CORRECTIONS" in text:
        st.warning("Validator verdict: ACCEPTED WITH CORRECTIONS")
    elif "ACCEPTED" in text:
        st.success("Validator verdict: ACCEPTED")


st.set_page_config(page_title="FSS demo", layout="wide")
st.title("Failure Synthesis System: demo")
st.caption("Recorded binary events -> bounded retrieval -> deterministic decoder -> "
           "evidence -> domain docs -> LLM (stub) -> output validator")

label = st.sidebar.selectbox("Scenario", list(SCENARIOS))
short = st.sidebar.checkbox("Short output (--short)", value=False)

if st.sidebar.button("Run", type="primary"):
    out, err, rc = run_demo(SCENARIOS[label], short)
    if rc != 0:
        st.error(f"run_demo.py exited with {rc}")
    if err.strip():
        st.code(err)
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
else:
    st.info("Pick a scenario in the sidebar and press Run.")
