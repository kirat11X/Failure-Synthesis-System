"""One test per hard rule in handoff section 22, checked on the Python side.

Rules 2, 3, 4, 6 and 16 are also enforced by Java (fss-core tests). Rule 14 concerns the
LLM, which is not built yet, so P1 can only check the input side: the evidence handed to
an LLM contains decoded values and nothing else.
"""

import ast
import base64
import dataclasses
import json
import re
import struct

import pytest

from conftest import FIXTURE_NAMES, GOLDEN, ROOT
from fss_py.contract import ENVELOPE_HEADER_LEN, U64_MAX
from fss_py.decoder import decode, decode_all
from fss_py.evidence import build_evidence
from fss_py.model import ALL, DecodeStatus, EventRecord, RetrievalRequestError, RetrievalResult
from fss_py.retriever import MockRetriever
from fss_py.schema import parse_schema
from fss_py.wire import EnvelopeError, encode_envelope, frame_record, iter_envelopes

T0 = 1_791_454_020_000_000_000
HOUR = 3600 * 1_000_000_000


def all_fixture_records():
    return [r for name in FIXTURE_NAMES
            for r in iter_envelopes((GOLDEN / f"{name}.bin").read_bytes())]


def full_evidence(registry, shuffle_seed=None):
    r = MockRetriever.from_files(*sorted(GOLDEN.glob("*.bin")), shuffle_seed=shuffle_seed)
    result = r.retrieve(ALL, T0, T0 + HOUR, max_events=100)
    return build_evidence(decode_all(result.events, registry), retrieval=result)


def all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from all_keys(v)


def test_rule_01_python_never_reads_java_storage_files(tmp_path):
    # Only the fixture loader and the schema loader touch the filesystem.
    file_access = {}
    for path in sorted((ROOT / "fss_py").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                if name in {"open", "read_bytes", "read_text", "mmap"}:
                    file_access.setdefault(path.name, set()).add(name)
    assert set(file_access) <= {"retriever.py", "schema.py"}
    # There is no record reader, and a Java-framed record is refused as input.
    import fss_py.wire as wire
    assert not [n for n in dir(wire) if re.search(r"(read|decode|parse|iter|scan)_?records?", n, re.I)]
    store = tmp_path / "events.dat"
    store.write_bytes(frame_record(encode_envelope(EventRecord(1, T0, 0x10, bytes(6)))))
    with pytest.raises(EnvelopeError):
        MockRetriever.from_files(store)


def test_rule_02_java_owns_retrieval(registry):
    """Selection happens only in retrieve(); decoder and evidence never drop or filter events."""
    far_outside_any_window = EventRecord(7, 1, 0x10, struct.pack("<HI", 0, 0))
    records = all_fixture_records() + [far_outside_any_window]
    ev = build_evidence(decode_all(records, registry))
    assert len(ev["events"]) == len(records)


@pytest.mark.parametrize("start,end", [(T0, T0), (T0, T0 - 1), (0, U64_MAX), (T0, T0 + HOUR + 1)])
def test_rule_03_every_retrieval_is_time_bounded(start, end):
    r = MockRetriever(all_fixture_records())
    with pytest.raises(RetrievalRequestError):
        r.retrieve(ALL, start, end, max_events=10)
    with pytest.raises(TypeError):
        r.retrieve(ALL, max_events=10)  # no window at all cannot even be expressed


def test_rule_04_retrieval_returns_complete_event_records():
    assert [f.name for f in dataclasses.fields(EventRecord)] == [
        "source_id", "timestamp_ns", "event_type", "payload_bytes"]
    for name in FIXTURE_NAMES:
        raw = (GOLDEN / f"{name}.bin").read_bytes()
        records = MockRetriever.from_files(GOLDEN / f"{name}.bin").retrieve(
            ALL, T0, T0 + HOUR, max_events=100).events
        assert sum(ENVELOPE_HEADER_LEN + len(r.payload_bytes) for r in records) == len(raw)


def test_rule_05_producer_timestamp_preserved(registry):
    records = all_fixture_records() + [EventRecord(1, U64_MAX, 0x10, bytes(6))]
    decoded = decode_all(records, registry)
    assert [d.timestamp_ns for d in decoded] == [r.timestamp_ns for r in records]
    ev = build_evidence(decoded)
    assert sorted(e["timestamp_ns"] for e in ev["events"]) == sorted(r.timestamp_ns for r in records)


def test_rule_06_no_global_ordering_is_assumed(registry):
    baseline = full_evidence(registry)
    for seed in range(10):
        assert full_evidence(registry, shuffle_seed=seed) == baseline
    assert "No order across sources" in baseline["ordering"]
    assert baseline["clock_caveat"] is not None


def test_rule_07_payload_stays_binary_until_decoding():
    for name in FIXTURE_NAMES:
        raw = (GOLDEN / f"{name}.bin").read_bytes()
        offset = 0
        for r in MockRetriever.from_files(GOLDEN / f"{name}.bin").retrieve(
                ALL, T0, T0 + HOUR, max_events=100).events:
            assert type(r.payload_bytes) is bytes
            start = offset + ENVELOPE_HEADER_LEN
            assert r.payload_bytes == raw[start:start + len(r.payload_bytes)]
            offset = start + len(r.payload_bytes)


def test_rule_08_binary_decoding_is_deterministic(registry):
    from fss_py.schema import load_schema_file
    from conftest import SCHEMA
    records = all_fixture_records()
    a = [d.to_dict() for d in decode_all(records, registry)]
    b = [d.to_dict() for d in decode_all(records, load_schema_file(SCHEMA))]
    assert a == b


def test_rule_09_layout_never_reaches_the_llm(registry):
    keys = set(all_keys(full_evidence(registry)))
    assert not keys & {"offset", "size", "endian", "struct_format", "schema", "payload_bytes",
                       "payload_hex", "raw"}


def test_rule_10_unknown_event_types_are_not_guessed(registry):
    lidar_shaped = struct.pack("<HI", 17, 3)  # would decode as LIDAR_TIMEOUT if guessed
    d = decode(EventRecord(474, T0, 0x31, lidar_shaped), registry)
    assert d.decode_status is DecodeStatus.UNKNOWN_EVENT_TYPE
    assert (d.fields, d.event_name, d.interpreted_fields) == ({}, None, [])


def test_rule_11_unknown_payload_regions_remain_opaque(registry):
    [record] = iter_envelopes((GOLDEN / "partial_opaque.bin").read_bytes())
    d = decode(record, registry)
    assert d.decode_status is DecodeStatus.PARTIALLY_DECODED and d.unknown_bytes == 8
    schema_keys = {k for f in registry.get(0x30).fields for k in (f.name, f.enum_field) if k}
    assert set(d.fields) == schema_keys


def _uninterpreted_regions(record, decoded, registry):
    payload = record.payload_bytes
    if decoded.decode_status in (DecodeStatus.UNKNOWN_EVENT_TYPE, DecodeStatus.MALFORMED_PAYLOAD):
        return [payload] if payload else []
    covered = set()
    for f in registry.get(record.event_type).fields:
        covered.update(range(f.offset, f.offset + f.size))
    regions, run = [], bytearray()
    for i, b in enumerate(payload):
        if i in covered:
            if run:
                regions.append(bytes(run))
            run = bytearray()
        else:
            run.append(b)
    return regions + ([bytes(run)] if run else [])


def test_rule_12_unknown_bytes_are_never_given_to_the_llm(registry):
    records = all_fixture_records()
    decoded = decode_all(records, registry)
    text = json.dumps(build_evidence(decoded))
    regions = [reg for r, d in zip(records, decoded) for reg in _uninterpreted_regions(r, d, registry)
               if len(reg) >= 4]
    assert len(regions) >= 4  # 0x31 payload, two opaque tails, a truncated payload
    for reg in regions:
        forms = [base64.b64encode(reg).decode(), json.dumps(list(reg))[1:-1],
                 reg.decode("latin-1")]
        if any(c in reg.hex() for c in "abcdef"):  # all-digit hex could match a timestamp
            forms += [reg.hex(), reg.hex().upper()]
        for form in forms:
            assert form not in text, f"opaque bytes leaked as {form!r}"


def test_rule_13_domain_documentation_supplies_meaning():
    def lidar_registry(mapping):
        return parse_schema({"enums": {"lidar": mapping}, "event_types": {0x10: {
            "name": "LIDAR_STATUS", "version": 1, "fields": [
                {"name": "status_code", "offset": 0, "type": "u16", "size": 2, "endian": "little",
                 "enum": "lidar", "enum_field": "status_name"},
                {"name": "timeout_count", "offset": 2, "type": "u32", "size": 4,
                 "endian": "little"}]}}})
    record = EventRecord(298, T0, 0x10, struct.pack("<HI", 17, 3))
    documented = decode(record, lidar_registry({17: "LIDAR_TIMEOUT"}))
    renamed = decode(record, lidar_registry({17: "SCAN_LATE"}))
    undocumented = decode(record, lidar_registry({18: "SENSOR_DISCONNECTED"}))
    assert documented.fields["status_name"] == "LIDAR_TIMEOUT"
    assert renamed.fields["status_name"] == "SCAN_LATE"
    assert undocumented.fields["status_name"] == "UNKNOWN"
    assert documented.interpreted_fields == ["status_name"]
    assert documented.fields["status_code"] == undocumented.fields["status_code"] == 17


def test_rule_14_llm_input_is_only_decoded_evidence(registry):
    decoded = {d.event_id: d for d in decode_all(all_fixture_records(), registry)}
    for e in full_evidence(registry)["events"]:
        d = decoded[e["event_id"]]
        assert e["fields"] == d.to_dict()["fields"]
        assert set(e["interpreted_fields"]) <= set(e["fields"])


def test_rule_15_cross_agent_retrieval_through_all():
    r = MockRetriever.from_files(GOLDEN / "scenario_298_474.bin")
    everyone = r.retrieve(ALL, T0, T0 + HOUR, max_events=100).events
    only_474 = r.retrieve(474, T0, T0 + HOUR, max_events=100).events
    assert {e.source_id for e in everyone} == {298, 474, 901}
    assert {e.source_id for e in only_474} == {474}


def test_rule_16_storage_internals_stay_hidden(registry):
    assert [f.name for f in dataclasses.fields(RetrievalResult)] == ["request", "events", "truncated"]
    keys = set(all_keys(full_evidence(registry)))
    assert not keys & {"block", "block_id", "offset", "segment", "used_len", "storage_offset", "crc"}
