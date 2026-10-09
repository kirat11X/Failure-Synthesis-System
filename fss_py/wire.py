"""Contract v0 wire format: envelope encoding/decoding, CRC-32C and event_id.

Python handles only the *envelope* (wire format). The on-disk record framing
belongs to Java. ``frame_record`` exists only so the shared test vectors can be
checked byte-for-byte; there is deliberately no record reader here (hard rule 1).
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterator

from .contract import ENVELOPE_HEADER_LEN, MAGIC, MAX_PAYLOAD_LEN, VERSION
from .model import EventRecord

_HEADER = struct.Struct("<HBBIQII")
assert _HEADER.size == ENVELOPE_HEADER_LEN


class EnvelopeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _make_crc_table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ (0x82F63B78 if c & 1 else 0)
        table.append(c)
    return tuple(table)


_CRC_TABLE = _make_crc_table()


def crc32c(data: bytes) -> int:
    """CRC-32C (Castagnoli), table-driven."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc = _CRC_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def encode_envelope(record: EventRecord) -> bytes:
    return _HEADER.pack(MAGIC, VERSION, 0, record.source_id, record.timestamp_ns,
                        record.event_type, len(record.payload_bytes)) + record.payload_bytes


def _check_header(data: bytes, offset: int) -> int:
    """Validate the 24-byte header at ``offset``; return payload_len."""
    if len(data) - offset < ENVELOPE_HEADER_LEN:
        raise EnvelopeError("TOO_SHORT", f"{len(data) - offset} bytes; header needs "
                                         f"{ENVELOPE_HEADER_LEN}")
    magic, version, flags, _, _, _, payload_len = _HEADER.unpack_from(data, offset)
    if magic != MAGIC:
        raise EnvelopeError("BAD_MAGIC", f"magic 0x{magic:04X}, expected 0x{MAGIC:04X}")
    if version != VERSION:
        raise EnvelopeError("BAD_VERSION", f"version {version}, expected {VERSION}")
    if flags != 0:
        raise EnvelopeError("BAD_FLAGS", f"flags 0x{flags:02X}; v0 requires 0")
    if payload_len > MAX_PAYLOAD_LEN:
        raise EnvelopeError("PAYLOAD_TOO_LARGE", f"payload_len {payload_len} > {MAX_PAYLOAD_LEN}")
    return payload_len


def decode_envelope(data: bytes) -> EventRecord:
    """Decode exactly one envelope (no trailing bytes allowed)."""
    payload_len = _check_header(data, 0)
    if len(data) != ENVELOPE_HEADER_LEN + payload_len:
        raise EnvelopeError("LENGTH_MISMATCH", f"{len(data)} bytes, header declares "
                                               f"{ENVELOPE_HEADER_LEN + payload_len}")
    _, _, _, source_id, ts, etype, _ = _HEADER.unpack_from(data, 0)
    return EventRecord(source_id, ts, etype, bytes(data[ENVELOPE_HEADER_LEN:]))


def iter_envelopes(data: bytes) -> Iterator[EventRecord]:
    """Decode an envelope stream (concatenated envelopes, e.g. a golden fixture)."""
    offset = 0
    while offset < len(data):
        payload_len = _check_header(data, offset)
        end = offset + ENVELOPE_HEADER_LEN + payload_len
        if end > len(data):
            raise EnvelopeError("LENGTH_MISMATCH", f"envelope at byte {offset} declares "
                                                   f"{end - offset} bytes; stream has "
                                                   f"{len(data) - offset}")
        yield decode_envelope(data[offset:end])
        offset = end


def event_id(record: EventRecord) -> str:
    """Content-derived id: "ev-" + first 12 hex digits of SHA-256(canonical envelope)."""
    return "ev-" + hashlib.sha256(encode_envelope(record)).hexdigest()[:12]


def frame_record(envelope: bytes) -> bytes:
    """Encode-only on-disk framing, used to check the shared vectors byte-for-byte."""
    length = struct.pack("<I", len(envelope))
    return length + struct.pack("<I", crc32c(length + envelope)) + envelope
