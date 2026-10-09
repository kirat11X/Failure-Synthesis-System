"""FSS Python layer (P1): deterministic decoding and evidence building. No LLM yet."""

from .decoder import decode, decode_all
from .evidence import build_evidence
from .model import (ALL, DecodedEvent, DecodeStatus, EventRecord, RetrievalRequest,
                    RetrievalRequestError, RetrievalResult)
from .retriever import MockRetriever, Retriever
from .schema import SchemaError, SchemaRegistry, load_schema_file, load_schema_text

__all__ = [
    "ALL", "DecodeStatus", "DecodedEvent", "EventRecord", "MockRetriever", "Retriever",
    "RetrievalRequest", "RetrievalRequestError", "RetrievalResult", "SchemaError",
    "SchemaRegistry", "build_evidence", "decode", "decode_all", "load_schema_file",
    "load_schema_text",
]
