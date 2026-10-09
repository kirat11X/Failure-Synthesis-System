"""Shared paths and helpers for the P1 test suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "contract" / "vectors"
GOLDEN = ROOT / "fixtures" / "golden"
EXPECTED = ROOT / "fixtures" / "expected"
SCHEMA = ROOT / "schemas" / "drone_v0.yaml"

FIXTURE_NAMES = sorted(p.stem for p in GOLDEN.glob("*.bin"))


def read_tsv(name: str) -> list[dict[str, str]]:
    lines = [ln for ln in (VECTORS / name).read_text().splitlines() if not ln.startswith("#")]
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"), strict=True)) for ln in lines[1:] if ln]


def expected_decoded(name: str) -> list[dict]:
    return json.loads((EXPECTED / f"{name}.decoded.json").read_text())


@pytest.fixture(scope="session")
def registry():
    from fss_py.schema import load_schema_file
    return load_schema_file(SCHEMA)
