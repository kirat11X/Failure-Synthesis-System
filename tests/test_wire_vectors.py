"""Shared contract vectors: Python must match them byte-for-byte (Java runs the same files)."""

import pytest

from conftest import read_tsv
from fss_py.model import EventRecord
from fss_py.wire import (EnvelopeError, crc32c, decode_envelope, encode_envelope, event_id,
                         frame_record, iter_envelopes)


@pytest.mark.parametrize("row", read_tsv("crc32c.tsv"), ids=lambda r: r["name"])
def test_crc32c_vectors(row):
    assert f"{crc32c(bytes.fromhex(row['input_hex'])):08x}" == row["crc32c"]


@pytest.mark.parametrize("row", read_tsv("envelope.tsv"), ids=lambda r: r["name"])
def test_envelope_vectors_round_trip(row):
    record = EventRecord(int(row["source_id"]), int(row["timestamp_ns"]), int(row["event_type"]),
                         bytes.fromhex(row["payload_hex"]))
    envelope = encode_envelope(record)
    assert envelope.hex() == row["envelope_hex"]
    assert frame_record(envelope).hex() == row["record_hex"]
    assert event_id(record) == row["event_id"]
    assert decode_envelope(bytes.fromhex(row["envelope_hex"])) == record


@pytest.mark.parametrize("row", read_tsv("envelope_reject.tsv"), ids=lambda r: r["name"])
def test_envelope_reject_vectors(row):
    with pytest.raises(EnvelopeError) as exc:
        decode_envelope(bytes.fromhex(row["envelope_hex"]))
    assert exc.value.code == row["error"]


def test_envelope_stream_rejects_trailing_partial_envelope():
    rows = read_tsv("envelope.tsv")
    stream = b"".join(bytes.fromhex(r["envelope_hex"]) for r in rows)
    assert len(list(iter_envelopes(stream))) == len(rows)
    with pytest.raises(EnvelopeError) as exc:
        list(iter_envelopes(stream[:-1]))
    assert exc.value.code == "LENGTH_MISMATCH"
