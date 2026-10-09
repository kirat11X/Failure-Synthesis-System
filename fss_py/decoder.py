"""Deterministic payload decoder: EventRecord + schema -> DecodedEvent.

Bounds are checked before every read, and decoding is all-or-nothing: a payload
that contradicts its schema yields MALFORMED_PAYLOAD with no field values.
Unknown event types and uncovered bytes stay unknown. Nothing is guessed.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from typing import Any

from .contract import UNKNOWN_LABEL
from .model import DecodedEvent, DecodeStatus, EventRecord
from .schema import EventSchema, FieldDef, SchemaRegistry
from .wire import event_id


def decode(record: EventRecord, registry: SchemaRegistry) -> DecodedEvent:
    payload = record.payload_bytes
    common = dict(event_id=event_id(record), source_id=record.source_id,
                  timestamp_ns=record.timestamp_ns, event_type=record.event_type,
                  payload_len=len(payload))
    schema = registry.get(record.event_type)
    if schema is None:
        return DecodedEvent(**common, event_name=None, schema_version=None,
                            decode_status=DecodeStatus.UNKNOWN_EVENT_TYPE, fields={},
                            interpreted_fields=[], unknown_bytes=len(payload), reason=None,
                            warnings=[])

    fields: dict[str, Any] = {}
    interpreted: list[str] = []
    warnings: list[str] = []
    for f in schema.fields:
        if f.offset + f.size > len(payload):
            return _malformed(common, schema, f"field '{f.name}' needs bytes "
                                              f"{f.offset}..{f.offset + f.size - 1} but payload "
                                              f"has {len(payload)} bytes")
        raw = struct.unpack_from(f.struct_format, payload, f.offset)[0]
        if f.type == "bool":
            if raw not in (0, 1):
                return _malformed(common, schema, f"field '{f.name}' is bool but byte {f.offset} "
                                                  f"has value {raw} (expected 0 or 1)")
            value: Any = bool(raw)
        elif f.type == "f32":
            value = _shortest_f32(raw)
        else:
            value = raw
        if isinstance(value, float) and not math.isfinite(value):
            warnings.append(f"field '{f.name}' decoded to a non-finite value ({value})")
        fields[f.name] = value
        if f.enum_map is not None:
            fields[f.enum_field] = _enum_label(f, value, warnings)
            interpreted.append(f.enum_field)

    unknown = len(payload) - sum(f.size for f in schema.fields)
    status = DecodeStatus.SUCCESS if unknown == 0 else DecodeStatus.PARTIALLY_DECODED
    return DecodedEvent(**common, event_name=schema.name, schema_version=schema.version,
                        decode_status=status, fields=fields, interpreted_fields=interpreted,
                        unknown_bytes=unknown, reason=None, warnings=warnings)


def decode_all(records: Iterable[EventRecord], registry: SchemaRegistry) -> list[DecodedEvent]:
    return [decode(r, registry) for r in records]


def _malformed(common: dict, schema: EventSchema, reason: str) -> DecodedEvent:
    return DecodedEvent(**common, event_name=schema.name, schema_version=schema.version,
                        decode_status=DecodeStatus.MALFORMED_PAYLOAD, fields={},
                        interpreted_fields=[], unknown_bytes=common["payload_len"],
                        reason=reason, warnings=[])


def _enum_label(f: FieldDef, value: int, warnings: list[str]) -> str:
    label = f.enum_map.get(value)
    if label is None:
        warnings.append(f"{f.name}={value} has no mapping in enum '{f.enum}'")
        return UNKNOWN_LABEL
    return label


def _shortest_f32(value: float) -> float:
    """Shortest decimal that maps back to the same f32 (72.4, not 72.4000015258789)."""
    if not math.isfinite(value):
        return value
    packed = struct.pack("<f", value)
    for digits in range(1, 10):
        candidate = float(f"{value:.{digits}g}")
        try:
            if struct.pack("<f", candidate) == packed:
                return candidate
        except OverflowError:  # rounding up past FLT_MAX
            continue
    return value
