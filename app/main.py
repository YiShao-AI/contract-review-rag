"""FastAPI app: upload documents, list them, ask cited questions."""
from __future__ import annotations

import csv
import hashlib
import os
import io
import json
import queue
import secrets
import threading
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .fetch_url import fetch as fetch_document
from .ingest import extract_metadata, ingest_file
from .validate import validate as validate_meta
from .rag import answer_question, stream_events
from .store import store
from .telemetry import (bind_request_id, current_request_id, event, opaque_ref,
                        request_id_from_header, reset_request_id)

app = FastAPI(title="Contract Review RAG")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ALLOWED = {".pdf", ".docx", ".txt"}


class AskRequest(BaseModel):
    question: str
    doc_id: int | None = None          # legacy single-document scope
    doc_ids: list[int] | None = None   # multi-document scope
    history: list[dict] | None = None  # [{role: user|assistant, content: str}]

    def scope(self) -> list[int] | None:
        ids = list(self.doc_ids or [])
        if self.doc_id is not None and self.doc_id not in ids:
            ids.append(self.doc_id)
        return ids or None


class ChatUpsert(BaseModel):
    title: str
    ts: int
    msgs: list[dict]


class LoginRequest(BaseModel):
    password: str


class UrlIngest(BaseModel):
    url: str
    name: str | None = None


class MetaPatch(BaseModel):
    meta: dict


# ── optional auth ──
# When APP_PASSWORD is set, every /api route (except login) requires a session
# cookie. Sessions live in memory: a server restart just means logging in again.
# The HTML page itself stays public — it contains no data and renders a login
# overlay on 401.
_sessions: set[str] = set()


@app.middleware("http")
async def request_boundary(request, call_next):
    """Apply shared-password auth and privacy-safe request correlation."""
    request_id = request_id_from_header(request.headers.get("X-Request-ID"))
    token = bind_request_id(request_id)
    started = time.perf_counter()
    try:
        path = request.url.path
        if (settings.app_password and path.startswith("/api")
                and path != "/api/login"
                and request.cookies.get("session", "") not in _sessions):
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            event("authentication_refused", method=request.method)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        route = getattr(request.scope.get("route"), "path", "unmatched")
        event("http_request", method=request.method, route_template=route,
              status_code=response.status_code,
              duration_ms=round((time.perf_counter() - started) * 1000, 2))
        return response
    except Exception as exc:
        event("http_request_failed", level=40, method=request.method,
              route_template=getattr(request.scope.get("route"), "path", "unmatched"),
              error_type=type(exc).__name__,
              duration_ms=round((time.perf_counter() - started) * 1000, 2))
        raise
    finally:
        reset_request_id(token)


@app.post("/api/login")
def login(req: LoginRequest):
    if settings.app_password and not secrets.compare_digest(
        req.password, settings.app_password
    ):
        raise HTTPException(401, "Wrong password.")
    resp = JSONResponse({"ok": True})
    if settings.app_password:
        token = secrets.token_urlsafe(32)
        _sessions.add(token)
        resp.set_cookie("session", token, httponly=True, samesite="lax",
                        secure=settings.cookie_secure)
    return resp


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health/live")
def health_live():
    return {"status": "ok", "service": "contract-review-rag"}


@app.get("/health/ready")
def health_ready():
    snapshot = store.health_snapshot()
    event("readiness_check", ready=snapshot["ready"],
          database=snapshot["database"], vector_index=snapshot["vector_index"],
          documents=snapshot.get("documents"), chunks=snapshot.get("chunks"),
          vectors=snapshot.get("vectors"), error_type=snapshot.get("error_type"))
    body = {
        "status": "ready" if snapshot["ready"] else "not_ready",
        "checks": {
            "database": snapshot["database"],
            "vector_index": snapshot["vector_index"],
        },
    }
    return JSONResponse(body, status_code=200 if snapshot["ready"] else 503)


@app.get("/api/docs")
def list_docs():
    return {"documents": store.list_documents()}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


MAX_UPLOAD_BYTES = 60 * 1024 * 1024   # matches the share-link fetcher
MAX_DOCX_ENTRIES = 2000
MAX_DOCX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 500


def _validate_document_bytes(data: bytes, suffix: str) -> None:
    """Reject mislabeled and pathologically compressed uploads before parsing."""
    if suffix == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise ValueError("The uploaded .pdf does not have a valid PDF header.")
        return
    if suffix == ".txt":
        if b"\x00" in data[:8192]:
            raise ValueError("The uploaded .txt appears to be binary data.")
        return
    if suffix != ".docx":
        return
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            expanded = sum(entry.file_size for entry in entries)
            compressed = sum(max(1, entry.compress_size) for entry in entries)
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError("The uploaded .docx is missing required document parts.")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise ValueError("Encrypted .docx archives are not supported.")
            if len(entries) > MAX_DOCX_ENTRIES or expanded > MAX_DOCX_EXPANDED_BYTES:
                raise ValueError("The uploaded .docx expands beyond the processing limit.")
            if expanded and expanded / compressed > MAX_DOCX_COMPRESSION_RATIO:
                raise ValueError("The uploaded .docx has an unsafe compression ratio.")
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded .docx is not a valid DOCX archive.") from exc


def _reserve_upload(safe_name: str, suffix: str, file_hash: str, data: bytes) -> Path:
    """Create a uniquely-named file and write the bytes into it.

    The name carries a prefix of the content hash, so two different documents
    can never collide even when uploaded under the same original filename, and
    identical content never reaches here (it is deduplicated above). The file
    is created with O_EXCL so two concurrent uploads cannot both believe they
    own the path — the previous exists()-then-write left the second upload
    silently overwriting the first, and made two documents share one file.
    """
    stem = Path(safe_name).stem[:80] or "document"
    for width in (8, 16, 64):
        candidate = settings.upload_dir / f"{stem}-{file_hash[:width]}{suffix}"
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue      # hash-prefix collision: lengthen and retry
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except Exception:
            candidate.unlink(missing_ok=True)
            raise
        return candidate
    raise HTTPException(500, "Could not allocate a unique filename for this upload.")


def _ingest_stream(data: bytes, raw_name: str, name: str | None):
    """Shared by file upload and share-link import: dedupe, persist, then
    stream ingestion progress as server-sent events."""
    safe_name = Path(raw_name or "").name
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or suffix not in ALLOWED:
        raise HTTPException(400, f"Unsupported type {suffix!r}. Allowed: {sorted(ALLOWED)}")
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"File is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        )
    try:
        _validate_document_bytes(data, suffix)
    except ValueError as exc:
        event("upload_rejected", reason_code="invalid_file_structure",
              file_extension=suffix, size_bytes=len(data))
        raise HTTPException(400, str(exc)) from exc

    file_hash = hashlib.sha256(data).hexdigest()

    # Dedupe: identical content is already indexed — don't index it twice.
    existing = store.find_by_hash(file_hash)
    if existing:
        event("ingest_duplicate", document_ref=opaque_ref(existing["id"]),
              file_extension=suffix, size_bytes=len(data))
        return StreamingResponse(
            iter([_sse({"type": "result", "duplicate": True, **existing})]),
            media_type="text/event-stream",
        )

    dest = _reserve_upload(safe_name, suffix, file_hash, data)
    display_name = name or Path(safe_name).stem
    request_id = current_request_id()
    event("ingest_accepted", file_extension=suffix, size_bytes=len(data),
          artifact_ref=file_hash[:12])

    def events():
        q: queue.Queue = queue.Queue()
        outcome: dict = {}

        def on_progress(stage, done=None, total=None):
            q.put({"type": "progress", "stage": stage, "done": done, "total": total})

        def work():
            worker_token = bind_request_id(request_id)
            try:
                outcome["result"] = ingest_file(
                    dest, display_name=display_name,
                    file_hash=file_hash, on_progress=on_progress,
                )
            except Exception as e:
                outcome["error"] = str(e)
                outcome["error_type"] = type(e).__name__
            finally:
                q.put(None)  # sentinel: done
                reset_request_id(worker_token)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        while (item := q.get()) is not None:
            yield _sse(item)
        worker.join()
        if "error" in outcome:
            # Safe to remove: _reserve_upload created this path exclusively, so
            # it cannot belong to another document.
            dest.unlink(missing_ok=True)
            event("ingest_failed", level=40, request_id=request_id,
                  file_extension=suffix, error_type=outcome.get("error_type"),
                  artifact_ref=file_hash[:12])
            yield _sse({"type": "error",
                        "message": f"Document processing failed. Reference: {request_id}"})
        else:
            event("ingest_completed", request_id=request_id,
                  document_ref=opaque_ref(outcome["result"]["doc_id"]),
                  file_extension=suffix, artifact_ref=file_hash[:12])
            yield _sse({"type": "result", **outcome["result"]})

    return StreamingResponse(events(), media_type="text/event-stream")


# Sync endpoints on purpose: FastAPI runs them in a threadpool, so parsing and
# embedding a large document doesn't block the event loop.
@app.post("/api/ingest")
def ingest(file: UploadFile = File(...), name: str = Form(None)):
    # Never trust the client filename: strip any path components.
    # Read at most one byte beyond the accepted limit so an oversized upload is
    # rejected without loading an arbitrarily large request body into memory.
    return _ingest_stream(
        file.file.read(MAX_UPLOAD_BYTES + 1), file.filename or "", name
    )


@app.post("/api/ingest-url")
def ingest_url(req: UrlIngest):
    """Import a document from a share link (Drive/Dropbox/OneDrive/direct)."""
    try:
        data, filename = fetch_document(req.url, ALLOWED)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _ingest_stream(data, filename, req.name)


@app.post("/api/ask")
def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty.")
    return answer_question(req.question, doc_ids=req.scope(), history=req.history)


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty.")
    return StreamingResponse(
        stream_events(req.question, doc_ids=req.scope(), history=req.history),
        media_type="text/event-stream",
    )


_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


@app.get("/api/docs/{doc_id}/file")
def doc_file(doc_id: int):
    """Serve the original uploaded file. Browsers render PDFs natively and
    honor #page=N fragments, giving citation click-through to the real page."""
    doc = store.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    path = settings.upload_dir / doc["filename"]
    if not path.exists():
        raise HTTPException(404, "Original file is missing.")
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        content_disposition_type="inline",
        filename=doc["filename"],
    )


@app.patch("/api/docs/{doc_id}/meta")
def patch_meta(doc_id: int, req: MetaPatch):
    """Correct extracted metadata by hand.

    Extraction is never perfect and a wrong value is costly — a bad expiry
    quietly removes a contract from every renewal view — so the operator needs
    to be able to fix it. Edits are validated the same way extraction is.
    """
    doc = store.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    current = next((d for d in store.list_documents() if d["id"] == doc_id), None)
    merged = {**((current or {}).get("meta") or {}), **req.meta}
    merged.pop("_rejected", None)          # a manual edit clears prior rejections
    cleaned, rejected = validate_meta(merged)
    if rejected:
        raise HTTPException(
            400, f"Invalid value for: {', '.join(rejected)}"
        )
    store.update_meta(doc_id, cleaned)
    return {"ok": True, "meta": cleaned}


@app.get("/api/export.csv")
def export_csv():
    """The portfolio as a spreadsheet — the thing you take to a renewal
    meeting or hand to someone who does not use this app."""
    cols = ["id", "counterparty", "contract_type", "street", "city", "state", "zip",
            "effective_date", "expiration_date", "days_left", "notice_days",
            "notice_by", "status", "renewal_type", "action", "compensation_model", "amount",
            "amount_period", "commission_rate", "governing_law",
            "contact_name", "contact_email", "contact_phone", "needs_review", "filename"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for d in store.list_documents():
        m = d.get("meta") or {}
        a = m.get("address") or {}
        c = m.get("contact") or {}
        r = d.get("renewal") or {}
        w.writerow([
            d["id"], d.get("counterparty", ""), m.get("contract_type", ""),
            a.get("street", ""), a.get("city", ""), a.get("state", ""), a.get("zip", ""),
            m.get("effective_date", ""), r.get("expires_on", ""), r.get("days_left", ""),
            m.get("notice_days", ""), r.get("notice_by", ""), r.get("status", ""),
            m.get("renewal_type", ""), r.get("action", ""), m.get("compensation_model", ""), m.get("amount", ""),
            m.get("amount_period", ""), m.get("commission_rate", ""),
            m.get("governing_law", ""),
            c.get("name", ""), c.get("email", ""), c.get("phone", ""),
            "; ".join(d.get("review") or []), d.get("filename", ""),
        ])
    return Response(
        buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="contracts.csv"'},
    )


@app.post("/api/docs/rescan")
def rescan_meta(only_missing: bool = True):
    """Re-extract document metadata from already-stored text.

    Adds fields introduced after a document was ingested (location, expiry,
    notice period, contact) without re-parsing files or re-computing
    embeddings — one LLM call per document. Streams progress.
    """
    docs = store.list_documents()
    targets = [
        d for d in docs
        if not only_missing or (d.get("review") or [])
    ]

    def events():
        yield _sse({"type": "start", "total": len(targets)})
        updated = 0
        for i, d in enumerate(targets, start=1):
            text = store.document_text(d["id"])
            meta = extract_metadata(text) if text else None
            if meta:
                # Only fill blanks. A null from a re-extraction must never
                # erase a value that is already there, least of all one the
                # operator corrected by hand.
                fresh = {k: v for k, v in meta.items() if v not in (None, "", [], {})}
                merged = {**(d.get("meta") or {}), **fresh}
                store.update_meta(d["id"], merged)
                updated += 1
            yield _sse({"type": "progress", "done": i, "total": len(targets),
                        "name": d.get("title") or d["name"]})
        yield _sse({"type": "result", "updated": updated, "total": len(targets)})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: int):
    if not store.delete_document(doc_id):
        raise HTTPException(404, "Document not found.")
    return {"deleted": doc_id}


# ── server-side chat history (incognito chats never reach these) ──

@app.get("/api/chats")
def list_chats():
    return {"chats": store.list_chats()}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = store.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found.")
    return chat


@app.put("/api/chats/{chat_id}")
def put_chat(chat_id: str, req: ChatUpsert):
    if len(chat_id) > 64:
        raise HTTPException(400, "Invalid chat id.")
    store.upsert_chat(chat_id, req.title, req.ts, req.msgs)
    return {"ok": True}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    if not store.delete_chat(chat_id):
        raise HTTPException(404, "Chat not found.")
    return {"deleted": chat_id}


@app.get("/api/chunk/{chunk_id}")
def chunk_context(chunk_id: int, window: int = 2):
    ctx = store.get_chunk_context(chunk_id, window=window)
    if ctx is None:
        raise HTTPException(404, "Chunk not found.")
    return ctx


# Serve the rest of the static assets (if any are added later).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
