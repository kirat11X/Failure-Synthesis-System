#!/usr/bin/env python3
"""FSS contract v0 fixture and test-vector generator (milestone M0).

This script is the *oracle* for the contract. It deliberately does not import
``fss_py``: it packs bytes with its own ``struct`` calls, computes CRC-32C bit by
bit, and writes the expected decoder output from the values it packed (never by
decoding). The Python decoder and the Java codec are both tested against it.

Usage (from the repo root):
    python fixtures/generate_fixtures.py          # (re)write every generated file
    python fixtures/generate_fixtures.py --check  # exit 1 if committed files are stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- contract v0
MAGIC = 0xF55A
VERSION = 1
ENVELOPE_HEADER = struct.Struct("<HBBIQII")  # magic ver flags source ts type payload_len
assert ENVELOPE_HEADER.size == 24
RECORD_HEADER_LEN = 8
BLOCK_SIZE = 65536
MAX_PAYLOAD_LEN = BLOCK_SIZE - RECORD_HEADER_LEN - ENVELOPE_HEADER.size  # 65504

# 2026-10-08T10:07:00Z in ns since the Unix epoch (fixture clock basis: UTC).
T0 = 1_791_454_020_000_000_000
MS = 1_000_000


def at(minute_offset: int, seconds: float) -> int:
    """Timestamp at 10:(07+minute_offset):<seconds> UTC, in ns (ms precision)."""
    return T0 + minute_offset * 60_000 * MS + round(seconds * 1000) * MS


# ------------------------------------------------------------------ encoding
def crc32c(data: bytes) -> int:
    """Bit-at-a-time CRC-32C (Castagnoli, reflected poly 0x82F63B78)."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


# Independent known answers: the standard check value and RFC 3720 appendix B.4.
_KNOWN_CRC32C = {
    b"123456789": 0xE3069283,
    bytes(32): 0x8A9136AA,
    b"\xff" * 32: 0x62A8AB43,
    bytes(range(32)): 0x46DD794E,
    bytes(range(31, -1, -1)): 0x113FDB5C,
}
for _data, _crc in _KNOWN_CRC32C.items():
    assert crc32c(_data) == _crc, f"CRC-32C self-check failed for {_data!r}"


def envelope(source_id: int, ts: int, etype: int, payload: bytes, *,
             magic: int = MAGIC, version: int = VERSION, flags: int = 0,
             payload_len: int | None = None) -> bytes:
    plen = len(payload) if payload_len is None else payload_len
    return ENVELOPE_HEADER.pack(magic, version, flags, source_id, ts, etype, plen) + payload


def record(env: bytes, *, record_len: int | None = None, crc: int | None = None) -> bytes:
    rlen = len(env) if record_len is None else record_len
    if crc is None:
        crc = crc32c(struct.pack("<I", rlen) + env)
    return struct.pack("<II", rlen, crc) + env


def event_id(env: bytes) -> str:
    return "ev-" + hashlib.sha256(env).hexdigest()[:12]


# ------------------------------------------- payload layouts (oracle's copy)
# These mirror schemas/drone_v0.yaml but are written independently of it.
LIDAR_STATUS, AVOIDANCE, FORMATION_STATE, DIAGNOSTIC = 0x10, 0x20, 0x21, 0x30
UNCONFIGURED_TYPE = 0x31

LIDAR_NAMES = {0: "OK", 17: "LIDAR_TIMEOUT", 18: "SENSOR_DISCONNECTED", 19: "INVALID_SCAN"}
DIAG_NAMES = {0: "NOMINAL", 1: "DEGRADED", 2: "FAULT"}
AVOID_NAMES = {1: "COLLISION_RISK", 2: "GEOFENCE", 3: "OPERATOR_COMMAND"}
FORMATION_NAMES = {0: "IN_FORMATION", 1: "LEFT_FORMATION", 2: "REJOINING"}


def _expected(env: bytes, source: int, ts: int, etype: int, payload: bytes, *,
              name: str | None, status: str, fields: dict, interpreted: list[str],
              unknown_bytes: int = 0, reason: str | None = None,
              warnings: list[str] | None = None) -> dict:
    return {
        "event_id": event_id(env),
        "source_id": source,
        "timestamp_ns": ts,
        "event_type": etype,
        "event_name": name,
        "schema_version": 1 if name else None,
        "decode_status": status,
        "fields": fields,
        "interpreted_fields": interpreted,
        "unknown_bytes": unknown_bytes,
        "reason": reason,
        "warnings": warnings or [],
        "payload_len": len(payload),
    }


def lidar(source: int, ts: int, status_code: int, timeout_count: int):
    payload = struct.pack("<HI", status_code, timeout_count)
    env = envelope(source, ts, LIDAR_STATUS, payload)
    label = LIDAR_NAMES.get(status_code, "UNKNOWN")
    warnings = [] if status_code in LIDAR_NAMES else [
        f"status_code={status_code} has no mapping in enum 'lidar_status'"]
    exp = _expected(env, source, ts, LIDAR_STATUS, payload, name="LIDAR_STATUS", status="SUCCESS",
                    fields={"status_code": status_code, "status_name": label,
                            "timeout_count": timeout_count},
                    interpreted=["status_name"], warnings=warnings)
    return env, exp


def avoidance(source: int, ts: int, reason_code: int, min_sep: float, heading: int):
    # min_sep is a short decimal literal, so it is also the shortest decimal that
    # round-trips through f32: exactly what the decoder must report.
    payload = struct.pack("<Bfh", reason_code, min_sep, heading)
    env = envelope(source, ts, AVOIDANCE, payload)
    exp = _expected(env, source, ts, AVOIDANCE, payload, name="AVOIDANCE", status="SUCCESS",
                    fields={"reason_code": reason_code, "reason": AVOID_NAMES[reason_code],
                            "min_separation_m": min_sep, "heading_change_deg": heading},
                    interpreted=["reason"])
    return env, exp


def formation(source: int, ts: int, state_code: int, formation_id: int):
    payload = struct.pack("<BH", state_code, formation_id)
    env = envelope(source, ts, FORMATION_STATE, payload)
    exp = _expected(env, source, ts, FORMATION_STATE, payload, name="FORMATION_STATE",
                    status="SUCCESS",
                    fields={"state_code": state_code, "state": FORMATION_NAMES[state_code],
                            "formation_id": formation_id},
                    interpreted=["state"])
    return env, exp


def diagnostic(source: int, ts: int, status_code: int, temperature_c: float, opaque: bytes):
    payload = struct.pack("<Hf", status_code, temperature_c) + opaque
    env = envelope(source, ts, DIAGNOSTIC, payload)
    exp = _expected(env, source, ts, DIAGNOSTIC, payload, name="DIAGNOSTIC",
                    status="PARTIALLY_DECODED" if opaque else "SUCCESS",
                    fields={"status_code": status_code, "status_name": DIAG_NAMES[status_code],
                            "temperature_c": temperature_c},
                    interpreted=["status_name"], unknown_bytes=len(opaque))
    return env, exp


def unconfigured(source: int, ts: int, payload: bytes):
    env = envelope(source, ts, UNCONFIGURED_TYPE, payload)
    exp = _expected(env, source, ts, UNCONFIGURED_TYPE, payload, name=None,
                    status="UNKNOWN_EVENT_TYPE", fields={}, interpreted=[],
                    unknown_bytes=len(payload))
    return env, exp


def malformed_lidar(source: int, ts: int, payload: bytes, reason: str):
    env = envelope(source, ts, LIDAR_STATUS, payload)
    exp = _expected(env, source, ts, LIDAR_STATUS, payload, name="LIDAR_STATUS",
                    status="MALFORMED_PAYLOAD", fields={}, interpreted=[],
                    unknown_bytes=len(payload), reason=reason)
    return env, exp


# Distinctive bytes so tests can prove they never leak into LLM evidence.
OPAQUE_8 = bytes.fromhex("a73c5e91d208f46b")
OPAQUE_8_B = bytes.fromhex("c4e1179b3a5d06f2")
UNCONFIGURED_12 = bytes.fromhex("31b7e2094dc8a65f1e7390bd")


# ------------------------------------------------------------------ fixtures
def fixtures() -> dict[str, list[tuple[bytes, dict]]]:
    """Fixture name -> events in *arrival order* (the order they sit in the .bin)."""
    scenario = [
        formation(474, at(0, 1.200), 0, 7),
        formation(298, at(0, 1.210), 0, 7),
        formation(901, at(0, 1.230), 0, 7),
        lidar(298, at(0, 2.500), 0, 0),
        # 474's avoidance arrives before 298's timeout; arrival order means nothing.
        avoidance(474, at(0, 3.120), 1, 3.2, -35),
        lidar(298, at(0, 3.050), 17, 3),
        diagnostic(298, at(0, 3.060), 1, 72.4, OPAQUE_8),
        formation(474, at(0, 3.180), 1, 7),
        formation(901, at(0, 3.300), 0, 7),
    ]
    truncated_payload = struct.pack("<HI", 17, 3)[:4]
    # True timeline: 115's LiDAR times out at 10:09:05.000 and 220 reacts 80 ms later.
    # 115's clock runs 250 ms fast, so its producer timestamp is *after* 220's reaction.
    skew = [
        avoidance(220, at(2, 5.080), 1, 2.6, 40),
        formation(220, at(2, 5.140), 1, 3),
        lidar(115, at(2, 5.250), 17, 2),
    ]
    return {
        "scenario_298_474": scenario,
        "unknown_type_0x31": [unconfigured(474, at(1, 1.000), UNCONFIGURED_12)],
        "partial_opaque": [diagnostic(298, at(1, 2.000), 2, 81.5, OPAQUE_8_B)],
        "malformed_truncated": [
            malformed_lidar(298, at(1, 3.000), truncated_payload,
                            "field 'timeout_count' needs bytes 2..5 but payload has 4 bytes"),
            malformed_lidar(298, at(1, 3.100), b"",
                            "field 'status_code' needs bytes 0..1 but payload has 0 bytes"),
        ],
        "unknown_enum": [lidar(298, at(1, 4.000), 99, 1)],
        "clock_skew_pair": skew,
    }


def skew_truth() -> dict:
    return {
        "description": ("Ground truth for clock_skew_pair. NOT decoder input. Drone 115's clock "
                        "runs 250 ms fast, so producer timestamps put 220's reaction before "
                        "115's LiDAR timeout, which actually caused it."),
        "clock_offset_ns": {"115": 250 * MS, "220": 0},
        "true_cause": {"source_id": 115, "event_name": "LIDAR_STATUS",
                       "true_time_ns": at(2, 5.000), "producer_timestamp_ns": at(2, 5.250)},
        "effects": [
            {"source_id": 220, "event_name": "AVOIDANCE",
             "true_time_ns": at(2, 5.080), "producer_timestamp_ns": at(2, 5.080)},
            {"source_id": 220, "event_name": "FORMATION_STATE",
             "true_time_ns": at(2, 5.140), "producer_timestamp_ns": at(2, 5.140)},
        ],
        "true_order": ["115:LIDAR_STATUS", "220:AVOIDANCE", "220:FORMATION_STATE"],
        "producer_timestamp_order": ["220:AVOIDANCE", "220:FORMATION_STATE", "115:LIDAR_STATUS"],
    }


# ------------------------------------------------------------------- vectors
def tsv(comment: str, header: list[str], rows: list[list[object]]) -> bytes:
    lines = [f"# {line}" if line else "#" for line in comment.strip().splitlines()]
    lines.append("\t".join(header))
    lines += ["\t".join(str(c) for c in row) for row in rows]
    return ("\n".join(lines) + "\n").encode()


def crc_vectors() -> bytes:
    lidar_env = envelope(298, at(0, 3.050), LIDAR_STATUS, struct.pack("<HI", 17, 3))
    cases = [
        ("check_123456789", b"123456789"),
        ("empty", b""),
        ("rfc3720_zeros_32", bytes(32)),
        ("rfc3720_ones_32", b"\xff" * 32),
        ("rfc3720_incrementing_32", bytes(range(32))),
        ("rfc3720_decrementing_32", bytes(range(31, -1, -1))),
        ("single_zero_byte", b"\x00"),
        ("ascii_text", b"Failure Synthesis System"),
        ("record_crc_input_lidar_timeout", struct.pack("<I", len(lidar_env)) + lidar_env),
    ]
    rows = [[name, data.hex(), f"{crc32c(data):08x}"] for name, data in cases]
    return tsv("""
CRC-32C (Castagnoli) known-answer vectors, shared by Java and Python.
Parameters: reflected poly 0x82F63B78, init 0xFFFFFFFF, xorout 0xFFFFFFFF.
input_hex: input bytes. crc32c: the u32 result as 8 lowercase hex digits (value, not byte order).
Generated by fixtures/generate_fixtures.py; rfc3720_* and check_* are independent known answers.
""", ["name", "input_hex", "crc32c"], rows)


def envelope_vectors() -> bytes:
    cases = [
        ("empty_payload", 1, 0, 0, b""),
        ("lidar_timeout_298", 298, at(0, 3.050), LIDAR_STATUS, struct.pack("<HI", 17, 3)),
        ("unsigned_extremes", 0xFFFFFFFF, 2**64 - 1, 0xFFFFFFFF, b"\xff"),
        ("high_bit_set", 2**31, 2**63, 2**31, b"\x00"),
        ("payload_1000", 474, at(0, 3.120), UNCONFIGURED_TYPE, bytes(i * 7 % 256 for i in range(1000))),
    ]
    rows = []
    for name, src, ts, et, payload in cases:
        env = envelope(src, ts, et, payload)
        rows.append([name, src, ts, et, payload.hex(), env.hex(), record(env).hex(), event_id(env)])
    return tsv("""
Envelope and record encoding vectors, shared by Java and Python. All integers little-endian.
source_id, timestamp_ns, event_type: unsigned decimal. payload_hex: raw payload.
envelope_hex: magic u16 | version u8 | flags u8 | source_id u32 | timestamp_ns u64 | event_type u32 | payload_len u32 | payload
record_hex:   record_len u32 | crc32c u32 | envelope   (record_len = envelope length; crc over record_len bytes + envelope)
event_id: "ev-" + first 12 hex digits of SHA-256(envelope).
Both sides must encode the fields to exactly envelope_hex/record_hex and decode envelope_hex back to the fields.
""", ["name", "source_id", "timestamp_ns", "event_type", "payload_hex", "envelope_hex",
      "record_hex", "event_id"], rows)


def envelope_reject_vectors() -> bytes:
    good = envelope(298, at(0, 3.050), LIDAR_STATUS, struct.pack("<HI", 17, 3))
    swapped = bytes([0xF5, 0x5A]) + good[2:]
    cases = [
        ("too_short_23", good[:23], "TOO_SHORT"),
        ("bad_magic", envelope(298, 1, 16, b"ab", magic=0xF55B), "BAD_MAGIC"),
        ("magic_big_endian", swapped, "BAD_MAGIC"),
        ("bad_version_2", envelope(298, 1, 16, b"ab", version=2), "BAD_VERSION"),
        ("bad_version_0", envelope(298, 1, 16, b"ab", version=0), "BAD_VERSION"),
        ("nonzero_flags", envelope(298, 1, 16, b"ab", flags=1), "BAD_FLAGS"),
        ("payload_too_large", envelope(298, 1, 16, b"", payload_len=MAX_PAYLOAD_LEN + 1),
         "PAYLOAD_TOO_LARGE"),
        ("payload_shorter_than_declared", envelope(298, 1, 16, b"abcde", payload_len=6),
         "LENGTH_MISMATCH"),
        ("payload_longer_than_declared", envelope(298, 1, 16, b"abcdefg", payload_len=6),
         "LENGTH_MISMATCH"),
    ]
    rows = [[name, data.hex(), err] for name, data, err in cases]
    return tsv("""
Envelopes that a decoder must reject, with the error code it must report.
The input is exactly one envelope (no trailing bytes). Checks run in this order and the first failure wins:
TOO_SHORT (< 24 bytes), BAD_MAGIC, BAD_VERSION, BAD_FLAGS, PAYLOAD_TOO_LARGE (> 65504), LENGTH_MISMATCH (length != 24 + payload_len).
""", ["name", "envelope_hex", "error"], rows)


def record_reject_vectors() -> bytes:
    payload = struct.pack("<HI", 17, 3)
    good_env = envelope(298, at(0, 3.050), LIDAR_STATUS, payload)
    good = record(good_env)
    flipped_payload = bytearray(good)
    flipped_payload[-1] ^= 0x04
    flipped_crc = bytearray(good)
    flipped_crc[5] ^= 0x01
    longer_len = record(good_env + b"\x00", crc=struct.unpack("<I", good[4:8])[0])
    assert crc32c(longer_len[:4] + longer_len[8:]) != struct.unpack("<I", longer_len[4:8])[0]

    def valid_crc(env: bytes) -> bytes:
        return record(env)

    cases = [
        ("ok_control", 128, good, "OK"),
        ("record_len_below_header", 128, record(good_env[:23]), "BAD_LENGTH"),
        ("record_len_exceeds_block", 128, struct.pack("<II", 200, 0) + good_env,
         "LENGTH_EXCEEDS_BLOCK"),
        ("payload_bit_flip", 128, bytes(flipped_payload), "CRC_MISMATCH"),
        ("crc_field_bit_flip", 128, bytes(flipped_crc), "CRC_MISMATCH"),
        ("record_len_plus_one", 128, longer_len, "CRC_MISMATCH"),
        ("crc_ok_bad_magic", 128, valid_crc(envelope(298, 1, 16, payload, magic=0x1234)), "BAD_MAGIC"),
        ("crc_ok_bad_version", 128, valid_crc(envelope(298, 1, 16, payload, version=9)), "BAD_VERSION"),
        ("crc_ok_bad_flags", 128, valid_crc(envelope(298, 1, 16, payload, flags=0x80)), "BAD_FLAGS"),
        ("crc_ok_length_mismatch", 128,
         valid_crc(envelope(298, 1, 16, payload + b"\x00", payload_len=6)), "LENGTH_MISMATCH"),
    ]
    rows = [[name, remaining, data.hex(), err] for name, remaining, data, err in cases]
    return tsv("""
On-disk record validation vectors (Java recovery only; Python never reads storage records).
block_remaining: bytes from the record start to the end of its block. Place record_hex at offset 0
of a zero-filled buffer of that size. Checks run in this order and the first failure wins:
BAD_LENGTH (record_len < 24), LENGTH_EXCEEDS_BLOCK (8 + record_len > block_remaining), CRC_MISMATCH,
then the envelope checks on the record_len envelope bytes (BAD_MAGIC, BAD_VERSION, BAD_FLAGS,
PAYLOAD_TOO_LARGE, LENGTH_MISMATCH). record_len == 0 is the end-of-block marker, not an error.
""", ["name", "block_remaining", "record_hex", "error"], rows)


# ---------------------------------------------------------------------- main
def build() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name, events in fixtures().items():
        for env, _ in events:
            assert len(env) - 24 <= MAX_PAYLOAD_LEN
        out[f"fixtures/golden/{name}.bin"] = b"".join(env for env, _ in events)
        expected = [exp for _, exp in events]
        out[f"fixtures/expected/{name}.decoded.json"] = (
            json.dumps(expected, indent=2) + "\n").encode()
    out["fixtures/expected/clock_skew_pair.truth.json"] = (
        json.dumps(skew_truth(), indent=2) + "\n").encode()
    out["contract/vectors/crc32c.tsv"] = crc_vectors()
    out["contract/vectors/envelope.tsv"] = envelope_vectors()
    out["contract/vectors/envelope_reject.tsv"] = envelope_reject_vectors()
    out["contract/vectors/record_reject.tsv"] = record_reject_vectors()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify the committed files match; write nothing")
    args = parser.parse_args()
    files = build()
    if args.check:
        stale = [p for p, data in files.items()
                 if not (ROOT / p).is_file() or (ROOT / p).read_bytes() != data]
        for p in stale:
            print(f"STALE: {p}", file=sys.stderr)
        print(f"{len(files) - len(stale)}/{len(files)} generated files up to date")
        return 1 if stale else 0
    for p, data in files.items():
        (ROOT / p).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / p).write_bytes(data)
        print(f"wrote {p} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
