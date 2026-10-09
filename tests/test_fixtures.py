"""M0 golden fixtures: committed files are current, and 100% decode to the expected JSON."""

import subprocess
import sys

import pytest

from conftest import FIXTURE_NAMES, GOLDEN, ROOT, expected_decoded
from fss_py.decoder import decode_all
from fss_py.wire import iter_envelopes


def test_fixture_set_is_complete():
    assert FIXTURE_NAMES == sorted([
        "clock_skew_pair", "malformed_truncated", "partial_opaque", "scenario_298_474",
        "unknown_enum", "unknown_type_0x31"])


def test_generated_files_are_current():
    """Regenerating must reproduce every committed fixture/vector byte-for-byte."""
    result = subprocess.run([sys.executable, str(ROOT / "fixtures" / "generate_fixtures.py"),
                             "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_decodes_to_expected_json(name, registry):
    records = list(iter_envelopes((GOLDEN / f"{name}.bin").read_bytes()))
    decoded = [d.to_dict() for d in decode_all(records, registry)]
    assert decoded == expected_decoded(name)
