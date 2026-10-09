"""python -m fss_py: fixture -> MockRetriever -> decoder -> evidence JSON (the P1 demo).

Example:
    python -m fss_py --fixture fixtures/golden/scenario_298_474.bin \
        --start 2026-10-08T10:07:00Z --end 2026-10-08T10:07:10Z \
        --query "Why did Drone 474 leave formation?"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from .decoder import decode_all
from .evidence import build_evidence
from .model import ALL, RetrievalRequestError
from .retriever import MockRetriever
from .schema import load_schema_file

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_time_ns(text: str) -> int:
    """Integer nanoseconds, or an ISO-8601 time with an explicit zone (µs precision)."""
    if text.isdigit():
        return int(text)
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{text!r}: give a timezone, e.g. a trailing Z")
    return (dt - _EPOCH) // timedelta(microseconds=1) * 1000


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m fss_py", description=__doc__.splitlines()[0])
    p.add_argument("--schema", default="schemas/drone_v0.yaml")
    p.add_argument("--fixture", action="append", required=True,
                   help="envelope-stream file (repeatable)")
    p.add_argument("--source", default="ALL", help="source_id or ALL (default)")
    p.add_argument("--start", required=True, type=parse_time_ns, help="t_start (inclusive)")
    p.add_argument("--end", required=True, type=parse_time_ns, help="t_end (exclusive)")
    p.add_argument("--event-type", help="numeric id (e.g. 0x10) or schema name")
    p.add_argument("--max-events", type=int, default=100)
    p.add_argument("--query")
    p.add_argument("--output", choices=["evidence", "decoded", "both"], default="evidence")
    args = p.parse_args(argv)

    registry = load_schema_file(args.schema)
    source = ALL if args.source.upper() == "ALL" else int(args.source, 0)
    event_type = None
    if args.event_type is not None:
        try:
            event_type = int(args.event_type, 0)
        except ValueError:
            event_type = registry.type_id(args.event_type)

    retriever = MockRetriever.from_files(*args.fixture)
    try:
        result = retriever.retrieve(source, args.start, args.end, max_events=args.max_events,
                                    event_type=event_type)
    except RetrievalRequestError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2
    decoded = decode_all(result.events, registry)
    out: dict = {}
    if args.output in ("decoded", "both"):
        out["decoded"] = [d.to_dict() for d in decoded]
    if args.output in ("evidence", "both"):
        out["evidence"] = build_evidence(decoded, query=args.query, retrieval=result)
    print(json.dumps(out if args.output == "both" else next(iter(out.values())), indent=2))
    return 0
