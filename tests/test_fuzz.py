"""Hypothesis-style fuzzing with a seeded stdlib RNG (no extra dependencies).

Properties: decode() never raises, never returns SUCCESS (or any field values) for a
payload shorter than its schema, and every value it does return equals an independent
struct.unpack of the same bytes.

Override with FSS_FUZZ_SEED / FSS_FUZZ_ITERATIONS. A failure prints the seed and iteration.
"""

import json
import math
import os
import random
import struct

import pytest

from conftest import FIXTURE_NAMES, GOLDEN
from fss_py.decoder import decode
from fss_py.model import DecodeStatus, EventRecord
from fss_py.schema import parse_schema
from fss_py.wire import EnvelopeError, iter_envelopes

SEED = int(os.environ.get("FSS_FUZZ_SEED", "20261008"))
ITERATIONS = int(os.environ.get("FSS_FUZZ_ITERATIONS", "20000"))


def _f(name, offset, type_, size, endian="little", **kw):
    return {"name": name, "offset": offset, "type": type_, "size": size,
            **({"endian": endian} if size > 1 else {}), **kw}


FUZZ_SCHEMA = parse_schema({
    "enums": {"e8": {0: "ZERO", 1: "ONE", 200: "TWO_HUNDRED"}, "es": {-1: "NEG", 5: "FIVE"}},
    "event_types": {
        0x01: {"name": "ALL_INTS", "version": 1, "fields": [
            _f("a", 0, "u8", 1, enum="e8"), _f("b", 1, "u16", 2), _f("c", 3, "u32", 4, "big"),
            _f("d", 7, "u64", 8), _f("e", 15, "i8", 1, enum="es"), _f("f", 16, "i16", 2, "big"),
            _f("g", 18, "i32", 4), _f("h", 22, "i64", 8, "big")]},
        0x02: {"name": "FLOATS_AND_BOOL", "version": 1, "fields": [
            _f("x", 0, "f32", 4), _f("y", 4, "f64", 8, "big"), _f("z", 12, "bool", 1)]},
        0x03: {"name": "GAPPY", "version": 1, "fields": [
            _f("p", 2, "u16", 2), _f("q", 10, "f32", 4, "big")]},
        0x04: {"name": "EMPTY", "version": 1, "fields": []},
        0x05: {"name": "TINY", "version": 1, "fields": [_f("t", 0, "u8", 1)]},
    }})
TYPES = [0x01, 0x02, 0x03, 0x04, 0x05, 0x31, 0xFFFFFFFF]
STATUSES = set(DecodeStatus)


def extent(schema):
    return max((f.offset + f.size for f in schema.fields), default=0)


def check_invariants(d, record, registry):
    payload = record.payload_bytes
    assert d.decode_status in STATUSES
    assert (d.source_id, d.timestamp_ns, d.event_type) == (
        record.source_id, record.timestamp_ns, record.event_type)
    json.dumps(d.to_dict(), allow_nan=False)
    schema = registry.get(record.event_type)
    if schema is None:
        assert d.decode_status is DecodeStatus.UNKNOWN_EVENT_TYPE
        assert d.fields == {} and d.unknown_bytes == len(payload)
        return
    if len(payload) < extent(schema):  # short payload: never success, never values
        assert d.decode_status is DecodeStatus.MALFORMED_PAYLOAD
    if d.decode_status is DecodeStatus.MALFORMED_PAYLOAD:
        assert d.fields == {} and d.reason
        return
    allowed = {k for f in schema.fields for k in (f.name, f.enum_field) if k}
    assert set(d.fields) == allowed
    for f in schema.fields:
        raw = struct.unpack_from(f.struct_format, payload, f.offset)[0]
        got = d.fields[f.name]
        if f.type == "f32":
            assert (math.isnan(got) and math.isnan(raw)) or struct.pack("<f", got) == struct.pack(
                "<f", raw)
        elif f.type == "f64":
            assert (math.isnan(got) and math.isnan(raw)) or got == raw
        elif f.type == "bool":
            assert raw in (0, 1) and got is bool(raw)
        else:
            assert got == raw
        if f.enum_field:
            assert d.fields[f.enum_field] == f.enum_map.get(raw, "UNKNOWN")
    unknown = len(payload) - sum(f.size for f in schema.fields)
    assert d.unknown_bytes == unknown
    assert d.decode_status is (DecodeStatus.SUCCESS if unknown == 0
                               else DecodeStatus.PARTIALLY_DECODED)


def test_fuzz_random_payloads():
    rng = random.Random(SEED)
    seen = set()
    for i in range(ITERATIONS):
        etype = rng.choice(TYPES)
        n = rng.choice([rng.randint(0, 8), rng.randint(0, 40), rng.randint(0, 300)])
        record = EventRecord(rng.getrandbits(32), rng.getrandbits(64), etype, rng.randbytes(n))
        try:
            d = decode(record, FUZZ_SCHEMA)
            check_invariants(d, record, FUZZ_SCHEMA)
        except Exception as exc:  # pragma: no cover - reported with a reproducer
            pytest.fail(f"seed={SEED} iteration={i} record={record!r}: {exc!r}")
        seen.add(d.decode_status)
    assert seen == STATUSES  # the fuzzer reached every status


def test_fuzz_truncating_every_golden_payload(registry):
    for name in FIXTURE_NAMES:
        for record in iter_envelopes((GOLDEN / f"{name}.bin").read_bytes()):
            for cut in range(len(record.payload_bytes) + 1):
                short = EventRecord(record.source_id, record.timestamp_ns, record.event_type,
                                    record.payload_bytes[:cut])
                check_invariants(decode(short, registry), short, registry)


def test_fuzz_bit_flips_in_golden_payloads(registry):
    rng = random.Random(SEED + 1)
    records = [r for n in FIXTURE_NAMES for r in iter_envelopes((GOLDEN / f"{n}.bin").read_bytes())]
    for _ in range(ITERATIONS // 4):
        r = rng.choice(records)
        if not r.payload_bytes:
            continue
        flipped = bytearray(r.payload_bytes)
        flipped[rng.randrange(len(flipped))] ^= 1 << rng.randrange(8)
        mutated = EventRecord(r.source_id, r.timestamp_ns, r.event_type, bytes(flipped))
        check_invariants(decode(mutated, registry), mutated, registry)


def test_fuzz_envelope_streams_fail_cleanly():
    rng = random.Random(SEED + 2)
    golden = b"".join((GOLDEN / f"{n}.bin").read_bytes() for n in FIXTURE_NAMES)
    for _ in range(ITERATIONS // 10):
        data = bytearray(golden[:rng.randint(0, len(golden))])
        for _ in range(rng.randint(0, 3)):
            if data:
                data[rng.randrange(len(data))] = rng.getrandbits(8)
        try:
            records = list(iter_envelopes(bytes(data)))
        except EnvelopeError:
            continue
        assert all(isinstance(r, EventRecord) for r in records)
