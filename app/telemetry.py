"""Small, dependency-free operational event layer.

Events are structured JSON and deliberately omit request bodies, questions,
answers, document text, filenames, URLs, credentials, and cookies. This keeps
request correlation useful without turning logs into a second document store.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timezone


SERVICE = "contract-review-rag"
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="background"
)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_SENSITIVE_KEY = re.compile(
    r"question|prompt|answer|document.?text|chunk.?text|content|filename|"
    r"address|email|phone|password|secret|token|api.?key|authorization|cookie|url",
    re.IGNORECASE,
)

logger = logging.getLogger("contract_rag.events")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def request_id_from_header(value: str | None) -> str:
    """Accept a compact trace ID or replace untrusted header content."""
    candidate = (value or "").strip()
    return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else secrets.token_hex(16)


def bind_request_id(value: str):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def current_request_id() -> str:
    return _request_id.get()


def opaque_ref(value: object) -> str:
    """Correlate an internal object without logging its raw identifier."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def _safe_fields(fields: dict) -> dict:
    safe = {}
    for key, value in fields.items():
        safe[key] = "[REDACTED]" if _SENSITIVE_KEY.search(key) else value
    return safe


def event(name: str, *, level: int = logging.INFO,
          request_id: str | None = None, **fields) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level),
        "service": SERVICE,
        "event": name,
        "request_id": request_id or current_request_id(),
        **_safe_fields(fields),
    }
    logger.log(level, json.dumps(payload, sort_keys=True, default=str))
