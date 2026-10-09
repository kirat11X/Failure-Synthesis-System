"""Data shapes shared by the retriever, decoder and evidence builder."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .contract import MAX_EVENTS_LIMIT, MAX_PAYLOAD_LEN, MAX_WINDOW_NS, U32_MAX, U64_MAX


class _AllSources:
    """Sentinel for retrieve(source=ALL). Not an in-band source_id."""

    _instance: _AllSources | None = None

    def __new__(cls) -> _AllSources:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ALL"


ALL = _AllSources()


def _is_uint(value: object, max_value: int) -> bool:
    # bool is an int subclass; True must not silently mean source 1.
    return type(value) is int and 0 <= value <= max_value


@dataclass(frozen=True, slots=True)
class EventRecord:
    """One complete stored event, as returned by retrieval. No storage fields."""

    source_id: int
    timestamp_ns: int  # producer timestamp, preserved verbatim
    event_type: int
    payload_bytes: bytes

    def __post_init__(self) -> None:
        if not _is_uint(self.source_id, U32_MAX):
            raise ValueError(f"source_id must be a u32, got {self.source_id!r}")
        if not _is_uint(self.timestamp_ns, U64_MAX):
            raise ValueError(f"timestamp_ns must be a u64, got {self.timestamp_ns!r}")
        if not _is_uint(self.event_type, U32_MAX):
            raise ValueError(f"event_type must be a u32, got {self.event_type!r}")
        if type(self.payload_bytes) is not bytes:
            raise TypeError(f"payload_bytes must be bytes, got {type(self.payload_bytes).__name__}")
        if len(self.payload_bytes) > MAX_PAYLOAD_LEN:
            raise ValueError(f"payload is {len(self.payload_bytes)} bytes; max is {MAX_PAYLOAD_LEN}")


class DecodeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIALLY_DECODED = "PARTIALLY_DECODED"
    UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
    MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"


def json_safe(value: Any) -> Any:
    """Non-finite floats are not valid JSON; render them the way JavaScript does."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    return value


@dataclass(frozen=True)
class DecodedEvent:
    event_id: str
    source_id: int
    timestamp_ns: int
    event_type: int
    event_name: str | None
    schema_version: int | None
    decode_status: DecodeStatus
    fields: dict[str, Any]
    interpreted_fields: list[str]  # keys in `fields` that come from enum documentation
    unknown_bytes: int  # payload bytes not represented in `fields`
    reason: str | None  # set for MALFORMED_PAYLOAD
    warnings: list[str]
    payload_len: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source_id": self.source_id,
            "timestamp_ns": self.timestamp_ns,
            "event_type": self.event_type,
            "event_name": self.event_name,
            "schema_version": self.schema_version,
            "decode_status": str(self.decode_status),
            "fields": {k: json_safe(v) for k, v in self.fields.items()},
            "interpreted_fields": list(self.interpreted_fields),
            "unknown_bytes": self.unknown_bytes,
            "reason": self.reason,
            "warnings": list(self.warnings),
            "payload_len": self.payload_len,
        }


class RetrievalRequestError(ValueError):
    """The request violates the retrieval contract; it is rejected, never clamped."""


@dataclass(frozen=True)
class RetrievalRequest:
    source: int | _AllSources
    t_start_ns: int
    t_end_ns: int
    max_events: int
    event_type: int | None = None

    def __post_init__(self) -> None:
        if self.source is not ALL and not _is_uint(self.source, U32_MAX):
            raise RetrievalRequestError(f"source must be a u32 source_id or ALL, got {self.source!r}")
        for name in ("t_start_ns", "t_end_ns"):
            if not _is_uint(getattr(self, name), U64_MAX):
                raise RetrievalRequestError(f"{name} is required and must be a u64, got "
                                            f"{getattr(self, name)!r}")
        if self.t_end_ns <= self.t_start_ns:
            raise RetrievalRequestError("time range must satisfy t_end_ns > t_start_ns")
        if self.t_end_ns - self.t_start_ns > MAX_WINDOW_NS:
            raise RetrievalRequestError(f"time window {self.t_end_ns - self.t_start_ns} ns exceeds "
                                        f"MAX_WINDOW_NS={MAX_WINDOW_NS}")
        if not (type(self.max_events) is int and 1 <= self.max_events <= MAX_EVENTS_LIMIT):
            raise RetrievalRequestError(f"max_events must be in [1, {MAX_EVENTS_LIMIT}], got "
                                        f"{self.max_events!r}")
        if self.event_type is not None and not _is_uint(self.event_type, U32_MAX):
            raise RetrievalRequestError(f"event_type must be a numeric u32 or None, got "
                                        f"{self.event_type!r}")

    def matches(self, record: EventRecord) -> bool:
        return ((self.source is ALL or record.source_id == self.source)
                and self.t_start_ns <= record.timestamp_ns < self.t_end_ns
                and (self.event_type is None or record.event_type == self.event_type))


@dataclass(frozen=True)
class RetrievalResult:
    request: RetrievalRequest
    events: list[EventRecord]
    truncated: bool  # True iff more than request.max_events events matched
