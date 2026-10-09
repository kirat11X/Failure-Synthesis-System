"""Schema loader: every definition problem is rejected at load time, not discovered while decoding."""

import pytest

from fss_py.schema import SchemaError, load_schema_text, parse_schema


def field(name="a", offset=0, type="u16", size=2, endian="little", **extra):
    f = {"name": name, "offset": offset, "type": type, "size": size, **extra}
    if endian is not None:
        f["endian"] = endian
    return f


def doc(*fields, enums=None):
    return {"enums": enums if enums is not None else {"lvl": {0: "LOW", 1: "HIGH"}},
            "event_types": {0x01: {"name": "T", "version": 1, "fields": list(fields)}}}


def rejects(document, match):
    with pytest.raises(SchemaError, match=match):
        parse_schema(document)


def test_repo_schema_loads(registry):
    assert len(registry) == 4
    assert registry.type_id("LIDAR_STATUS") == 0x10
    assert 0x31 not in registry
    lidar = registry.get(0x10)
    assert [f.name for f in lidar.fields] == ["status_code", "timeout_count"]
    assert lidar.fields[0].enum_field == "status_name"


def test_fields_are_sorted_by_offset():
    reg = parse_schema(doc(field("b", offset=2), field("a", offset=0)))
    assert [f.name for f in reg.get(1).fields] == ["a", "b"]


def test_overlapping_fields_rejected():
    rejects(doc(field("a", 0, "u32", 4), field("b", 2, "u16", 2)), "overlap")


def test_adjacent_fields_accepted():
    parse_schema(doc(field("a", 0, "u32", 4), field("b", 4, "u16", 2)))


def test_size_type_mismatch_rejected():
    rejects(doc(field("a", 0, "u32", 2)), "size 2 does not match type u32")


def test_unknown_type_rejected():
    rejects(doc(field("a", 0, "u24", 3)), "unknown type 'u24'")


def test_endian_required_for_multibyte_types():
    rejects(doc(field("a", 0, "u16", 2, endian=None)), "endian .* required")


def test_endian_value_validated():
    rejects(doc(field("a", 0, "u16", 2, endian="native")), "endian must be")


def test_endian_optional_for_single_byte_types():
    reg = parse_schema(doc(field("a", 0, "u8", 1, endian=None), field("b", 1, "bool", 1, endian=None)))
    assert [f.endian for f in reg.get(1).fields] == [None, None]


def test_missing_required_key_rejected():
    f = field()
    del f["offset"]
    rejects(doc(f), "missing required key")


def test_unknown_field_key_rejected():
    rejects(doc(field(ofset=3)), "unknown key")


def test_unknown_top_level_key_rejected():
    d = doc(field())
    d["event_type"] = {}
    rejects(d, "unknown key")


def test_negative_offset_rejected():
    rejects(doc(field(offset=-1)), "offset must be an integer")


def test_field_beyond_max_payload_rejected():
    rejects(doc(field(offset=65503)), "offset must be an integer")


def test_duplicate_field_names_rejected():
    rejects(doc(field("a", 0), field("a", 2)), "used twice")


def test_enum_field_colliding_with_field_rejected():
    rejects(doc(field("a", 0, enum="lvl", enum_field="b"), field("b", 2)), "used twice")


def test_enum_field_defaults_to_name_suffix():
    reg = parse_schema(doc(field("mode", 0, "u8", 1, endian=None, enum="lvl")))
    assert reg.get(1).fields[0].enum_field == "mode_name"


def test_enum_reserved_unknown_label_rejected():
    rejects(doc(field(enum="lvl"), enums={"lvl": {0: "UNKNOWN"}}), "reserved")


def test_enum_only_on_integer_types():
    rejects(doc(field("t", 0, "f32", 4, enum="lvl")), "only allowed on integer types")
    rejects(doc(field("t", 0, "bool", 1, endian=None, enum="lvl")), "only allowed on integer types")


def test_undefined_enum_rejected():
    rejects(doc(field(enum="nope")), "not defined")


def test_enum_code_must_fit_field_type():
    rejects(doc(field("a", 0, "u8", 1, endian=None, enum="big"), enums={"big": {300: "X"}}),
            "does not fit u8")
    rejects(doc(field("a", 0, "u8", 1, endian=None, enum="neg"), enums={"neg": {-1: "X"}}),
            "does not fit u8")
    parse_schema(doc(field("a", 0, "i8", 1, endian=None, enum="neg"), enums={"neg": {-1: "X"}}))


def test_enum_field_without_enum_rejected():
    rejects(doc(field(enum_field="x")), "enum_field given without enum")


def test_empty_field_list_allowed():
    reg = parse_schema({"event_types": {7: {"name": "MARKER", "version": 1, "fields": []}}})
    assert reg.get(7).fields == ()


def test_event_type_id_must_be_u32():
    rejects({"event_types": {2**32: {"name": "X", "version": 1, "fields": []}}}, "event type id")


def test_duplicate_event_names_rejected():
    rejects({"event_types": {1: {"name": "X", "version": 1, "fields": []},
                             2: {"name": "X", "version": 1, "fields": []}}}, "duplicate event name")


def test_version_required():
    rejects({"event_types": {1: {"name": "X", "fields": []}}}, "version must be an integer")


# ---- YAML-level traps: these only show up when parsing text ----

def test_duplicate_yaml_keys_rejected():
    text = """
event_types:
  0x10: {name: A, version: 1, fields: []}
  0x10: {name: B, version: 1, fields: []}
"""
    with pytest.raises(SchemaError, match="duplicate key 16"):
        load_schema_text(text)


def test_duplicate_enum_code_rejected():
    text = """
enums:
  lvl: {0: LOW, 0: HIGH}
event_types:
  1: {name: A, version: 1, fields: []}
"""
    with pytest.raises(SchemaError, match="duplicate key 0"):
        load_schema_text(text)


def test_yaml_boolean_words_are_not_integers():
    text = "event_types:\n  1: {name: A, version: yes, fields: []}\n"
    with pytest.raises(SchemaError, match="version must be an integer"):
        load_schema_text(text)


def test_yaml_boolean_words_are_not_enum_labels():
    text = """
enums:
  sw: {0: OFF, 1: ON}
event_types:
  1: {name: A, version: 1, fields: [{name: s, offset: 0, type: u8, size: 1, enum: sw}]}
"""
    with pytest.raises(SchemaError, match="must be a non-empty string"):
        load_schema_text(text)


def test_invalid_yaml_reported_as_schema_error():
    with pytest.raises(SchemaError, match="invalid YAML"):
        load_schema_text("event_types: [unclosed")
