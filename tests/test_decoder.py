"""Decoder behaviour: primitives, the four statuses, enums, floats and determinism."""

import json
import math
import struct

import pytest

from fss_py.decoder import decode
from fss_py.model import DecodeStatus, EventRecord
from fss_py.schema import load_schema_file, parse_schema
from conftest import SCHEMA

TS = 1_791_454_023_050_000_000


def registry_for(*fields, enums=None, event_type=0x01, name="T"):
    return parse_schema({"enums": enums or {"lvl": {0: "LOW", 1: "HIGH"}},
                         "event_types": {event_type: {"name": name, "version": 3,
                                                      "fields": list(fields)}}})


def f(name, offset, type_, size, endian="little", **extra):
    out = {"name": name, "offset": offset, "type": type_, "size": size, **extra}
    if endian:
        out["endian"] = endian
    return out


def rec(payload, event_type=0x01, source=298, ts=TS):
    return EventRecord(source, ts, event_type, payload)


PRIMITIVE_CASES = [
    ("u8", "B", 255), ("u16", "H", 65535), ("u32", "I", 2**32 - 1), ("u64", "Q", 2**64 - 1),
    ("i8", "b", -128), ("i16", "h", -32768), ("i32", "i", -2**31), ("i64", "q", -2**63),
    ("f32", "f", 1.5), ("f64", "d", -2.25),
]


@pytest.mark.parametrize("endian,prefix", [("little", "<"), ("big", ">")])
@pytest.mark.parametrize("type_,code,value", PRIMITIVE_CASES)
def test_every_primitive_in_both_byte_orders(type_, code, value, endian, prefix):
    size = struct.calcsize(code)
    reg = registry_for(f("v", 0, type_, size, endian if size > 1 else None))
    d = decode(rec(struct.pack(prefix + code, value)), reg)
    assert d.decode_status is DecodeStatus.SUCCESS
    assert d.fields == {"v": value}
    assert type(d.fields["v"]) is type(value)


def test_same_bytes_signed_vs_unsigned():
    reg = registry_for(f("u", 0, "u16", 2), f("i", 2, "i16", 2))
    assert decode(rec(b"\xff\xff\xff\xff"), reg).fields == {"u": 65535, "i": -1}


def test_byte_order_is_taken_from_schema():
    little = registry_for(f("v", 0, "u16", 2, "little"))
    big = registry_for(f("v", 0, "u16", 2, "big"))
    assert decode(rec(b"\x01\x00"), little).fields["v"] == 1
    assert decode(rec(b"\x01\x00"), big).fields["v"] == 256


def test_bool_values():
    reg = registry_for(f("b", 0, "bool", 1, None))
    assert decode(rec(b"\x00"), reg).fields == {"b": False}
    assert decode(rec(b"\x01"), reg).fields == {"b": True}


def test_bool_with_other_value_is_malformed_not_guessed():
    reg = registry_for(f("x", 0, "u8", 1, None), f("b", 1, "bool", 1, None))
    d = decode(rec(b"\x05\x02"), reg)
    assert d.decode_status is DecodeStatus.MALFORMED_PAYLOAD
    assert d.fields == {}
    assert d.reason == "field 'b' is bool but byte 1 has value 2 (expected 0 or 1)"


def test_unknown_event_type():
    reg = registry_for(f("v", 0, "u8", 1, None))
    d = decode(rec(b"\x01\x02\x03", event_type=0x99), reg)
    assert d.decode_status is DecodeStatus.UNKNOWN_EVENT_TYPE
    assert (d.fields, d.event_name, d.schema_version, d.unknown_bytes) == ({}, None, None, 3)


def test_trailing_bytes_are_partially_decoded():
    reg = registry_for(f("v", 0, "u16", 2))
    d = decode(rec(b"\x07\x00" + bytes(8)), reg)
    assert d.decode_status is DecodeStatus.PARTIALLY_DECODED
    assert (d.fields, d.unknown_bytes) == ({"v": 7}, 8)


def test_gap_between_fields_counts_as_unknown():
    reg = registry_for(f("a", 0, "u8", 1, None), f("b", 4, "u8", 1, None))
    d = decode(rec(b"\x01\xaa\xbb\xcc\x02"), reg)
    assert d.decode_status is DecodeStatus.PARTIALLY_DECODED
    assert (d.fields, d.unknown_bytes) == ({"a": 1, "b": 2}, 3)


def test_out_of_bounds_field_is_malformed_with_no_fields():
    reg = registry_for(f("a", 0, "u16", 2), f("b", 8, "u32", 4))
    d = decode(rec(bytes(10)), reg)
    assert d.decode_status is DecodeStatus.MALFORMED_PAYLOAD
    assert d.fields == {} and d.interpreted_fields == []
    assert d.reason == "field 'b' needs bytes 8..11 but payload has 10 bytes"
    assert d.unknown_bytes == 10


def test_unmapped_enum_value_stays_unknown():
    reg = registry_for(f("mode", 0, "u8", 1, None, enum="lvl"))
    d = decode(rec(b"\x09"), reg)
    assert d.decode_status is DecodeStatus.SUCCESS
    assert d.fields == {"mode": 9, "mode_name": "UNKNOWN"}
    assert d.interpreted_fields == ["mode_name"]
    assert d.warnings == ["mode=9 has no mapping in enum 'lvl'"]


def test_signed_enum_codes():
    reg = registry_for(f("m", 0, "i8", 1, None, enum="s"), enums={"s": {-1: "REVERSE"}})
    assert decode(rec(b"\xff"), reg).fields == {"m": -1, "m_name": "REVERSE"}


@pytest.mark.parametrize("value,expected", [
    (72.4, 72.4), (0.1, 0.1), (-3.2, -3.2), (1e-45, 1e-45), (0.0, 0.0),
    (3.4028234663852886e38, 3.4028235e38),  # FLT_MAX: rounding up must not overflow
])
def test_f32_reported_as_shortest_round_trip(value, expected):
    reg = registry_for(f("x", 0, "f32", 4))
    out = decode(rec(struct.pack("<f", value)), reg).fields["x"]
    assert out == expected
    assert struct.pack("<f", out) == struct.pack("<f", value)


def test_negative_zero_preserved():
    reg = registry_for(f("x", 0, "f32", 4))
    out = decode(rec(struct.pack("<f", -0.0)), reg).fields["x"]
    assert out == 0.0 and math.copysign(1.0, out) == -1.0


@pytest.mark.parametrize("raw,json_value", [
    (struct.pack("<f", float("nan")), "NaN"),
    (struct.pack("<f", float("inf")), "Infinity"),
    (struct.pack("<f", float("-inf")), "-Infinity"),
])
def test_non_finite_floats_kept_with_warning_and_strict_json(raw, json_value):
    reg = registry_for(f("x", 0, "f32", 4))
    d = decode(rec(raw), reg)
    assert d.decode_status is DecodeStatus.SUCCESS
    assert len(d.warnings) == 1 and "non-finite" in d.warnings[0]
    data = d.to_dict()
    assert data["fields"]["x"] == json_value
    json.dumps(data, allow_nan=False)


def test_zero_field_schema():
    reg = parse_schema({"event_types": {5: {"name": "MARKER", "version": 1, "fields": []}}})
    assert decode(rec(b"", event_type=5), reg).decode_status is DecodeStatus.SUCCESS
    d = decode(rec(b"abc", event_type=5), reg)
    assert (d.decode_status, d.unknown_bytes) == (DecodeStatus.PARTIALLY_DECODED, 3)


def test_schema_version_comes_from_schema():
    reg = registry_for(f("v", 0, "u8", 1, None))
    assert decode(rec(b"\x01"), reg).schema_version == 3


def test_decoding_is_deterministic_across_registry_loads(registry):
    payload = struct.pack("<HI", 17, 3)
    first = decode(rec(payload, event_type=0x10), registry).to_dict()
    again = decode(rec(payload, event_type=0x10), load_schema_file(SCHEMA)).to_dict()
    assert first == again
