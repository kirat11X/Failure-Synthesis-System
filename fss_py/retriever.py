"""Retrieval contract on the Python side, plus a MockRetriever over golden fixtures.

The real Java client arrives in milestone I1. Until then MockRetriever enforces
the same contract (bounded window, max_events, truncated flag) so the rest of
the pipeline cannot depend on behaviour Java will not provide.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from .model import ALL, EventRecord, RetrievalRequest, RetrievalResult, _AllSources
from .wire import iter_envelopes

__all__ = ["ALL", "MockRetriever", "Retriever"]


class Retriever(Protocol):
    def retrieve(self, source: int | _AllSources, t_start_ns: int, t_end_ns: int, *,
                 max_events: int, event_type: int | None = None) -> RetrievalResult: ...


class MockRetriever:
    """In-memory retriever over EventRecords (normally loaded from envelope-stream fixtures).

    Results keep fixture (arrival) order unless ``shuffle_seed`` is set. Shuffling
    lets tests prove that consumers do not depend on an order that Java does not
    guarantee.
    """

    def __init__(self, events: Iterable[EventRecord], *, shuffle_seed: int | None = None) -> None:
        self._events = list(events)
        self._shuffle_seed = shuffle_seed

    @classmethod
    def from_files(cls, *paths: str | Path, shuffle_seed: int | None = None) -> MockRetriever:
        events: list[EventRecord] = []
        for path in paths:
            events.extend(iter_envelopes(Path(path).read_bytes()))
        return cls(events, shuffle_seed=shuffle_seed)

    def retrieve(self, source: int | _AllSources, t_start_ns: int, t_end_ns: int, *,
                 max_events: int, event_type: int | None = None) -> RetrievalResult:
        request = RetrievalRequest(source, t_start_ns, t_end_ns, max_events, event_type)
        matches = [r for r in self._events if request.matches(r)]
        if self._shuffle_seed is not None:
            random.Random(self._shuffle_seed).shuffle(matches)
        return RetrievalResult(request, matches[:max_events], truncated=len(matches) > max_events)
