"""Evidence builder: the LLM-context structure from handoff section 20 (output only)."""

import json

from conftest import GOLDEN, expected_decoded
from fss_py.decoder import decode_all
from fss_py.evidence import ORDERING_NOTE, build_evidence
from fss_py.model import ALL, EventRecord
from fss_py.retriever import MockRetriever

T0 = 1_791_454_020_000_000_000
SEC = 1_000_000_000


def evidence_for(registry, *names, start=T0, end=T0 + 3600 * SEC, max_events=100, **kw):
    r = MockRetriever.from_files(*(GOLDEN / f"{n}.bin" for n in names), **kw)
    result = r.retrieve(ALL, start, end, max_events=max_events)
    return build_evidence(decode_all(result.events, registry), query="q", retrieval=result)


def kinds(ev):
    return [g["kind"] for g in ev["data_gaps"]]


def test_scenario_evidence_shape(registry):
    ev = evidence_for(registry, "scenario_298_474", end=T0 + 10 * SEC)
    assert set(ev) == {"format", "query", "retrieval", "sources", "ordering", "clock_caveat",
                       "events", "data_gaps"}
    assert ev["sources"] == [298, 474, 901]
    assert ev["retrieval"] == {"source": "ALL", "t_start_ns": T0, "t_end_ns": T0 + 10 * SEC,
                               "event_type": None, "max_events": 100, "returned": 9,
                               "truncated": False}
    assert ev["ordering"] == ORDERING_NOTE
    assert "not synchronized" in ev["clock_caveat"] and "298, 474, 901" in ev["clock_caveat"]
    assert kinds(ev) == ["OPAQUE_BYTES"]
    assert ev["data_gaps"][0]["source_id"] == 298
    assert ev["data_gaps"][0]["detail"].startswith("8 payload bytes of DIAGNOSTIC (0x30)")
    json.dumps(ev, allow_nan=False)


def test_events_grouped_by_source_then_producer_time(registry):
    ev = evidence_for(registry, "scenario_298_474")
    keys = [(e["source_id"], e["timestamp_ns"]) for e in ev["events"]]
    assert keys == sorted(keys)


def test_event_entries_mirror_decoder_output(registry):
    ev = evidence_for(registry, "scenario_298_474")
    by_id = {d["event_id"]: d for d in expected_decoded("scenario_298_474")}
    for e in ev["events"]:
        d = by_id[e["event_id"]]
        assert e["fields"] == d["fields"]
        assert e["interpreted_fields"] == d["interpreted_fields"]
        assert e["timestamp_ns"] == d["timestamp_ns"]


def test_single_source_has_no_clock_caveat(registry):
    ev = evidence_for(registry, "unknown_enum")
    assert ev["sources"] == [298] and ev["clock_caveat"] is None


def test_gap_kinds_for_each_edge_case(registry):
    assert kinds(evidence_for(registry, "unknown_type_0x31")) == ["UNKNOWN_EVENT_TYPE"]
    assert kinds(evidence_for(registry, "partial_opaque")) == ["OPAQUE_BYTES"]
    assert kinds(evidence_for(registry, "malformed_truncated")) == ["MALFORMED_PAYLOAD"] * 2
    assert kinds(evidence_for(registry, "unknown_enum")) == ["UNMAPPED_ENUM"]
    assert kinds(evidence_for(registry, "clock_skew_pair")) == []


def test_malformed_event_carries_reason_but_no_values(registry):
    ev = evidence_for(registry, "malformed_truncated")
    for e in ev["events"]:
        assert e["fields"] == {} and e["decode_status"] == "MALFORMED_PAYLOAD"
        assert "needs bytes" in e["reason"]


def test_truncation_reported_as_gap(registry):
    ev = evidence_for(registry, "scenario_298_474", max_events=4)
    assert ev["retrieval"]["truncated"] is True and len(ev["events"]) == 4
    assert kinds(ev)[0] == "RETRIEVAL_TRUNCATED"


def test_duplicates_reported(registry):
    dup = EventRecord(298, T0, 0x10, b"\x00\x00\x00\x00\x00\x00")
    ev = build_evidence(decode_all([dup, dup], registry))
    assert kinds(ev) == ["DUPLICATE_EVENT"] and len(ev["events"]) == 2


def test_evidence_does_not_depend_on_retrieval_order(registry):
    plain = evidence_for(registry, "scenario_298_474", "clock_skew_pair")
    for seed in range(5):
        assert evidence_for(registry, "scenario_298_474", "clock_skew_pair",
                            shuffle_seed=seed) == plain


def test_clock_skew_pair_is_reported_not_corrected(registry):
    """Producer order contradicts the true cause; evidence keeps raw timestamps plus the caveat."""
    truth = json.loads((GOLDEN.parent / "expected" / "clock_skew_pair.truth.json").read_text())
    ev = evidence_for(registry, "clock_skew_pair")
    stamps = {(e["source_id"], e["event_name"]): e["timestamp_ns"] for e in ev["events"]}
    cause = truth["true_cause"]
    assert stamps[(115, "LIDAR_STATUS")] == cause["producer_timestamp_ns"]
    assert stamps[(115, "LIDAR_STATUS")] > stamps[(220, "AVOIDANCE")]  # skew is preserved
    assert cause["true_time_ns"] < stamps[(220, "AVOIDANCE")]  # yet 115 really came first
    assert ev["clock_caveat"] is not None
    assert "true_time_ns" not in json.dumps(ev)
