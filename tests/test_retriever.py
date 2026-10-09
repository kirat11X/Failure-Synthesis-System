"""MockRetriever enforces the v0 retrieval contract exactly as Java must."""

import pytest

from conftest import GOLDEN
from fss_py.contract import MAX_EVENTS_LIMIT, MAX_WINDOW_NS, U64_MAX
from fss_py.model import ALL, EventRecord, RetrievalRequestError
from fss_py.retriever import MockRetriever
from fss_py.wire import EnvelopeError, encode_envelope, frame_record

T0 = 1_791_454_020_000_000_000
SEC = 1_000_000_000
SCENARIO = GOLDEN / "scenario_298_474.bin"


@pytest.fixture
def scenario():
    return MockRetriever.from_files(SCENARIO)


def window(r, source=ALL, start=T0, end=T0 + 10 * SEC, **kw):
    kw.setdefault("max_events", 100)
    return r.retrieve(source, start, end, **kw)


def test_all_scenario_events_in_window(scenario):
    result = window(scenario)
    assert len(result.events) == 9 and not result.truncated


@pytest.mark.parametrize("start,end", [(T0, T0), (T0 + 1, T0), (0, U64_MAX),
                                       (T0, T0 + MAX_WINDOW_NS + 1)])
def test_unbounded_or_inverted_ranges_rejected(scenario, start, end):
    with pytest.raises(RetrievalRequestError):
        window(scenario, start=start, end=end)


def test_max_window_is_inclusive_limit(scenario):
    assert len(window(scenario, start=T0, end=T0 + MAX_WINDOW_NS).events) == 9


@pytest.mark.parametrize("bad", [None, -1, 1.5, "100"])
def test_time_bounds_must_be_u64(scenario, bad):
    with pytest.raises(RetrievalRequestError):
        window(scenario, start=bad)


def test_max_events_is_required(scenario):
    with pytest.raises(TypeError):
        scenario.retrieve(ALL, T0, T0 + SEC)


@pytest.mark.parametrize("bad", [0, -1, MAX_EVENTS_LIMIT + 1, True, 2.0])
def test_max_events_range(scenario, bad):
    with pytest.raises(RetrievalRequestError):
        window(scenario, max_events=bad)


def test_max_events_limits_accepted(scenario):
    assert len(window(scenario, max_events=1).events) == 1
    assert len(window(scenario, max_events=MAX_EVENTS_LIMIT).events) == 9


@pytest.mark.parametrize("max_events,returned,truncated", [(10, 9, False), (9, 9, False),
                                                           (8, 8, True), (1, 1, True)])
def test_truncated_flag_is_exact(scenario, max_events, returned, truncated):
    result = window(scenario, max_events=max_events)
    assert (len(result.events), result.truncated) == (returned, truncated)


def test_interval_is_half_open():
    r = MockRetriever([EventRecord(1, 100, 1, b""), EventRecord(1, 200, 1, b"")])
    assert [e.timestamp_ns for e in r.retrieve(ALL, 100, 200, max_events=10).events] == [100]
    assert [e.timestamp_ns for e in r.retrieve(ALL, 101, 201, max_events=10).events] == [200]


def test_source_and_type_filters(scenario):
    assert {e.source_id for e in window(scenario, source=474).events} == {474}
    lidar = window(scenario, event_type=0x10).events
    assert len(lidar) == 2 and {e.event_type for e in lidar} == {0x10}
    assert window(scenario, source=12345).events == []


@pytest.mark.parametrize("bad", ["ALL", -1, 2**32, True, None])
def test_source_must_be_u32_or_ALL(scenario, bad):
    with pytest.raises(RetrievalRequestError):
        window(scenario, source=bad)


def test_event_type_filter_is_numeric(scenario, registry):
    with pytest.raises(RetrievalRequestError):
        window(scenario, event_type="LIDAR_STATUS")
    assert len(window(scenario, event_type=registry.type_id("LIDAR_STATUS")).events) == 2


def test_unsigned_extreme_timestamps():
    top = U64_MAX - 1
    r = MockRetriever([EventRecord(2**32 - 1, top, 2**32 - 1, b"x")])
    assert len(r.retrieve(2**32 - 1, top, U64_MAX, max_events=1).events) == 1


def test_rejects_storage_framed_files(tmp_path):
    """Python only reads envelope streams; a Java-style framed record is refused."""
    framed = tmp_path / "store.dat"
    framed.write_bytes(frame_record(encode_envelope(EventRecord(298, T0, 0x10, b"\x11\x00"))))
    with pytest.raises(EnvelopeError, match="BAD_MAGIC"):
        MockRetriever.from_files(framed)


def test_shuffle_changes_order_not_content():
    plain = window(MockRetriever.from_files(SCENARIO)).events
    shuffled = window(MockRetriever.from_files(SCENARIO, shuffle_seed=7)).events
    assert shuffled != plain and sorted(shuffled, key=repr) == sorted(plain, key=repr)
