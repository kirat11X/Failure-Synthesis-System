"""Evidence builder: DecodedEvent list -> LLM-context structure (handoff section 20).

Output only, with no LLM call. The structure separates three kinds of information
(handoff section 14):
  * decoded facts:       ``fields`` minus ``interpreted_fields``
  * documented meaning:  ``interpreted_fields`` (enum labels from configuration)
  * unknown:             ``data_gaps`` (never the bytes themselves)
Payload bytes are never copied into the evidence (hard rule 12).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from .contract import UNKNOWN_LABEL
from .model import ALL, DecodedEvent, DecodeStatus, RetrievalResult, json_safe

EVIDENCE_FORMAT = "fss-evidence/v0"
ORDERING_NOTE = ("Events are grouped by source_id and sorted by producer timestamp within each "
                 "source. No order across sources is implied.")


def build_evidence(events: Sequence[DecodedEvent], *, query: str | None = None,
                   retrieval: RetrievalResult | None = None) -> dict[str, Any]:
    ordered = sorted(events, key=lambda e: (e.source_id, e.timestamp_ns, e.event_id))
    sources = sorted({e.source_id for e in events})

    gaps: list[dict[str, Any]] = []
    if retrieval is not None and retrieval.truncated:
        n = retrieval.request.max_events
        gaps.append({"kind": "RETRIEVAL_TRUNCATED", "event_id": None, "source_id": None,
                     "detail": f"More than max_events={n} events matched; only {n} are included "
                               f"and the omitted ones may include entire sources. Narrow the "
                               f"time window or filter by source/type and retrieve again."})
    for e in ordered:
        gaps.extend(_gaps_for(e))
    for eid, count in sorted(Counter(e.event_id for e in events).items()):
        if count > 1:
            gaps.append({"kind": "DUPLICATE_EVENT", "event_id": eid, "source_id": None,
                         "detail": f"Event {eid} appears {count} times with byte-identical "
                                   f"content."})

    return {
        "format": EVIDENCE_FORMAT,
        "query": query,
        "retrieval": _retrieval_summary(retrieval),
        "sources": sources,
        "ordering": ORDERING_NOTE,
        "clock_caveat": _clock_caveat(sources),
        "events": [_event_entry(e) for e in ordered],
        "data_gaps": gaps,
    }


def _type_label(e: DecodedEvent) -> str:
    hex_id = f"0x{e.event_type:02X}"
    return f"{e.event_name} ({hex_id})" if e.event_name else f"event type {hex_id}"


def _event_entry(e: DecodedEvent) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "event_id": e.event_id,
        "source_id": e.source_id,
        "timestamp_ns": e.timestamp_ns,
        "event_type": f"0x{e.event_type:02X}",
        "event_name": e.event_name,
        "decode_status": str(e.decode_status),
        "fields": {k: json_safe(v) for k, v in e.fields.items()},
        "interpreted_fields": list(e.interpreted_fields),
    }
    if e.unknown_bytes:
        entry["unknown_bytes"] = e.unknown_bytes
    if e.reason:
        entry["reason"] = e.reason
    if e.warnings:
        entry["warnings"] = list(e.warnings)
    return entry


def _gaps_for(e: DecodedEvent) -> list[dict[str, Any]]:
    where = f"{_type_label(e)} event {e.event_id} from source {e.source_id}"
    status = e.decode_status
    if status is DecodeStatus.UNKNOWN_EVENT_TYPE:
        detail = (f"Event {e.event_id} from source {e.source_id} has event type "
                  f"0x{e.event_type:02X}, which has no configured schema. Its {e.payload_len} "
                  f"payload bytes were preserved but not interpreted.")
        return [_gap("UNKNOWN_EVENT_TYPE", e, detail)]
    if status is DecodeStatus.MALFORMED_PAYLOAD:
        detail = (f"{where} could not be decoded ({e.reason}). None of its field values are "
                  f"available.")
        return [_gap("MALFORMED_PAYLOAD", e, detail)]
    gaps = []
    if status is DecodeStatus.PARTIALLY_DECODED:
        gaps.append(_gap("OPAQUE_BYTES", e, f"{e.unknown_bytes} payload bytes of {where} were not "
                                            f"decoded because their structure is not configured."))
    for key in e.interpreted_fields:
        if e.fields.get(key) == UNKNOWN_LABEL:
            gaps.append(_gap("UNMAPPED_ENUM", e, f"In {where}, '{key}' is {UNKNOWN_LABEL}: the "
                                                 f"decoded code has no documented meaning."))
    return gaps


def _gap(kind: str, e: DecodedEvent, detail: str) -> dict[str, Any]:
    return {"kind": kind, "event_id": e.event_id, "source_id": e.source_id, "detail": detail}


def _clock_caveat(sources: list[int]) -> str | None:
    if len(sources) <= 1:
        return None
    return (f"Events come from {len(sources)} sources ({', '.join(map(str, sources))}). Producer "
            f"clocks are not synchronized: each timestamp_ns reflects only its own producer's "
            f"clock. Comparing timestamps across sources does not establish order or causality, "
            f"so any cross-source sequence must be stated as uncertain.")


def _retrieval_summary(retrieval: RetrievalResult | None) -> dict[str, Any] | None:
    if retrieval is None:
        return None
    req = retrieval.request
    return {
        "source": "ALL" if req.source is ALL else req.source,
        "t_start_ns": req.t_start_ns,
        "t_end_ns": req.t_end_ns,
        "event_type": None if req.event_type is None else f"0x{req.event_type:02X}",
        "max_events": req.max_events,
        "returned": len(retrieval.events),
        "truncated": retrieval.truncated,
    }
