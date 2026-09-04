"""Local persistence: FAISS for vectors + SQLite for chunk text & metadata.

Both live on disk under DATA_DIR. The FAISS id of each vector matches the
`rowid` of its chunk in SQLite, so a vector hit maps straight back to its
source text, document, page, and section — which is what powers citations.

Search is hybrid: dense vectors (FAISS) fused with BM25 keyword ranking
(SQLite FTS5) via reciprocal-rank fusion. Contracts are exact-term-heavy
("Section 7.2", "indemnification"), so keyword recall matters.
"""
from __future__ import annotations

import json
import re
import os
import sqlite3
import threading
from datetime import date, timedelta
from typing import Iterable

import faiss
import numpy as np

from .config import settings
from .validate import review_flags

_RRF_K = 60  # standard reciprocal-rank-fusion constant

# Coarse bucket for filtering. In a real portfolio most agreements are the same
# kind (site placements) and a handful are suppliers, so this two-way split is
# far more useful to filter on than the raw contract_type string.
_SITE_WORDS = re.compile(
    r"lease|placement|rental|premises|site|space|licen[cs]e to (?:use|occupy)|tenan",
    re.IGNORECASE,
)


def _iso(value) -> "date | None":
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def renewal_view(meta: dict | None, today: "date | None" = None) -> dict:
    """Derived renewal facts: when it ends, by when notice must be given, and
    how urgent that is. The notice deadline is the date that actually matters —
    an auto-renewing lease rolls over silently once it passes."""
    today = today or date.today()
    end = _iso((meta or {}).get("expiration_date"))
    notice_days = (meta or {}).get("notice_days")
    notice_days = notice_days if isinstance(notice_days, (int, float)) else None
    rtype = (meta or {}).get("renewal_type") or (
        "auto" if (meta or {}).get("auto_renews") else None
    )
    out = {
        "expires_on": end.isoformat() if end else None,
        "days_left": (end - today).days if end else None,
        "notice_by": None,
        "notice_days_left": None,
        "renewal_type": rtype,
        # What missing the deadline costs. Under an operator option the
        # agreement simply ends, so the deadline is to KEEP the site; under an
        # auto-renewal it rolls over, so the deadline is to GET OUT.
        "action": {"auto": "cancel_by", "operator_option": "renew_by",
                   "mutual": "agree_by"}.get(rtype, "act_by"),
        "status": "unknown",
    }
    if end and notice_days:
        by = end - timedelta(days=int(notice_days))
        out["notice_by"] = by.isoformat()
        out["notice_days_left"] = (by - today).days
    if end:
        d = out["days_left"]
        nd = out["notice_days_left"]
        if d < 0:
            out["status"] = "expired"
        elif nd is not None and nd < 0:
            out["status"] = "notice_passed"   # auto-renewal window already missed
        elif (nd if nd is not None else d) <= 30:
            out["status"] = "urgent"
        elif (nd if nd is not None else d) <= 90:
            out["status"] = "soon"
        else:
            out["status"] = "ok"
    return out


_VENDOR_WORDS = re.compile(
    r"armored|cash-in-transit|transport|cellular|telecom|processing|"
    r"maintenance|insurance|software|服务|service agreement|supply|nda|"
    r"non-disclosure|employment|license agreement",
    re.IGNORECASE,
)


def document_kind(meta: dict | None) -> str:
    """Default to "site": the portfolio is overwhelmingly placement
    agreements, and guessing "vendor" for an unrecognised type would quietly
    exempt it from the site review checklist."""
    kind = str((meta or {}).get("contract_type") or "")
    if _SITE_WORDS.search(kind):
        return "site"
    return "vendor" if _VENDOR_WORDS.search(kind) else "site"

# Legal-entity suffixes, dropped so a title reads "Swiss Towers & Sunrise"
# rather than "Swiss Towers AG & Sunrise Communications AG".
_ENTITY_SUFFIX = re.compile(
    r"[,\s]+(?:inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|ag|gmbh|"
    r"n\.a|s\.a|sa|plc|lp|llp|holdings|group)\.?$",
    re.IGNORECASE,
)


# The ATM/kiosk operator's own names — recur on every agreement, so they are
# never the distinguishing counterparty.
_KNOWN_OPERATORS = ("getcoins", "evergreen atm")


def _short_party(party: str) -> str:
    name = party.strip().rstrip(".")
    while True:
        trimmed = _ENTITY_SUFFIX.sub("", name).strip().rstrip(",")
        if trimmed == name or not trimmed:
            break
        name = trimmed
    return name or party.strip()


def document_title(name: str, meta: dict | None) -> str:
    """A human-readable title for a contract, e.g. "Vendor Supply Agreement —
    Ironclad & Quartz". Uses the type and parties extracted at ingest; falls
    back to tidying the filename so a document without metadata still reads
    better than EDGAR_Master_Services_Agreement_Sunrise_Communications_AG."""
    if meta:
        kind = str(meta.get("contract_type") or "").strip()
        parties = [p.strip() for p in (meta.get("parties") or [])
                   if isinstance(p, str) and p.strip()]
        shorts = [_short_party(p) for p in parties[:2]]
        if kind and shorts:
            return f"{kind} — {' & '.join(shorts)}"
        if kind:
            return kind
    tidy = re.sub(r"^EDGAR[_\s-]+", "", name)
    return re.sub(r"_+", " ", tidy).strip() or name


class Store:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._readers = threading.local()
        self._reader_connections: list[sqlite3.Connection] = []
        self.db_path = settings.db_path
        self.index_path = settings.index_path
        self.upload_dir = settings.upload_dir
        self.db = sqlite3.connect(
            self.db_path, timeout=30, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self._init_db()
        self.index = self._load_index()
        self._check_consistency()

    def _reader_db(self) -> sqlite3.Connection:
        """Return one read-only SQLite connection per request thread.

        FastAPI executes synchronous handlers in a worker pool. Sharing the
        writer connection across those threads can produce intermittent
        ``sqlite3.InterfaceError`` failures even when every query is read-only.
        WAL plus thread-local readers permits concurrent retrieval while the
        primary connection remains the single serialized writer.
        """
        db = getattr(self._readers, "db", None)
        if db is None:
            db = sqlite3.connect(
                self.db_path, timeout=30, check_same_thread=False
            )
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA busy_timeout=30000")
            self._readers.db = db
            with self._lock:
                self._reader_connections.append(db)
        return db

    def close(self) -> None:
        """Close writer and any reader connections created by this instance."""
        with self._lock:
            for db in self._reader_connections:
                try:
                    db.close()
                except sqlite3.Error:
                    pass
            self._reader_connections.clear()
            self.db.close()

    def _check_consistency(self) -> None:
        """Chunks whose vectors never made it into the index are invisible to
        dense retrieval but still counted in the UI. Surface that rather than
        letting it rot silently."""
        rows = self.db.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
        have = self.index.ntotal if self.index is not None else 0
        self.orphan_chunks = max(0, rows - have)
        self.orphan_vectors = max(0, have - rows)
        if self.orphan_chunks or self.orphan_vectors:
            print(f"[store] WARNING: {rows} chunks but {have} vectors — "
                  f"{self.orphan_chunks} chunk(s) without a vector and "
                  f"{self.orphan_vectors} vector(s) without a chunk. "
                  f"Rebuild the index before serving retrieval.")

    def health_snapshot(self) -> dict:
        """Return storage/index readiness without exposing document content."""
        try:
            with self._lock:
                self.db.execute("SELECT 1").fetchone()
                documents = self.db.execute(
                    "SELECT COUNT(*) AS c FROM documents"
                ).fetchone()["c"]
                chunks = self.db.execute(
                    "SELECT COUNT(*) AS c FROM chunks"
                ).fetchone()["c"]
                fts_rows = self.db.execute(
                    "SELECT COUNT(*) AS c FROM chunks_fts"
                ).fetchone()["c"]
                vectors = self.index.ntotal if self.index is not None else 0
            ready = chunks == fts_rows == vectors
            return {
                "ready": ready,
                "database": "ok",
                "vector_index": "ok" if ready else "inconsistent",
                "documents": documents,
                "chunks": chunks,
                "fts_rows": fts_rows,
                "vectors": vectors,
            }
        except Exception as exc:
            return {
                "ready": False,
                "database": "error",
                "vector_index": "unknown",
                "error_type": type(exc).__name__,
            }

    # ── schema ──
    def _init_db(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                filename TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                file_hash TEXT,
                meta_json TEXT
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                page INTEGER,
                section TEXT,
                chunk_index INTEGER,
                text TEXT NOT NULL,
                FOREIGN KEY (doc_id) REFERENCES documents(id)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text);
            CREATE TABLE IF NOT EXISTS geocache (
                q TEXT PRIMARY KEY,
                lat REAL NOT NULL,
                lon REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                ts INTEGER NOT NULL,
                msgs_json TEXT NOT NULL
            );
            """
        )
        # Lightweight migrations for databases created by earlier versions.
        doc_cols = [r[1] for r in self.db.execute("PRAGMA table_info(documents)")]
        for col in ("file_hash", "meta_json"):
            if col not in doc_cols:
                self.db.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT")
        chunk_cols = [r[1] for r in self.db.execute("PRAGMA table_info(chunks)")]
        if "section" not in chunk_cols:
            self.db.execute("ALTER TABLE chunks ADD COLUMN section TEXT")
        # Backfill FTS for chunks indexed before the FTS table existed.
        self.db.execute(
            "INSERT INTO chunks_fts(rowid, text) "
            "SELECT id, text FROM chunks WHERE id NOT IN (SELECT rowid FROM chunks_fts)"
        )
        self.db.commit()

    def _load_index(self) -> faiss.Index | None:
        if not self.index_path.exists():
            return None  # created lazily on first add (dimension from first batch)
        try:
            return faiss.read_index(str(self.index_path))
        except Exception:
            # Never let an unreadable index stop the app from starting: the
            # documents and their text are still in SQLite and can be re-embedded.
            self.index_path.rename(
                self.index_path.with_suffix(".corrupt")
            )
            return None

    def _persist_index(self) -> None:
        """Write to a temp file and rename. write_index truncates in place, so
        a kill partway through would leave a truncated index that raises on
        read — and the app constructs Store() at import, so it would not boot."""
        if self.index is None:
            return
        tmp = self.index_path.with_suffix(".tmp")
        faiss.write_index(self.index, str(tmp))
        os.replace(tmp, self.index_path)

    # ── writes ──
    def add_document(self, name: str, filename: str, file_hash: str | None = None) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO documents (name, filename, file_hash) VALUES (?, ?, ?)",
                (name, filename, file_hash),
            )
            self.db.commit()
            return cur.lastrowid

    def update_meta(self, doc_id: int, meta: dict) -> None:
        with self._lock:
            self.db.execute(
                "UPDATE documents SET meta_json = ? WHERE id = ?",
                (json.dumps(meta), doc_id),
            )
            self.db.commit()

    def add_chunks(
        self, doc_id: int, chunks: list[dict], vectors: np.ndarray
    ) -> None:
        """chunks: [{page, section, chunk_index, text}]; vectors aligned by position."""
        with self._lock:
            if self.index is None:
                dim = vectors.shape[1]
                self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
            ids = []
            for ch in chunks:
                cur = self.db.execute(
                    "INSERT INTO chunks (doc_id, page, section, chunk_index, text) "
                    "VALUES (?,?,?,?,?)",
                    (doc_id, ch.get("page"), ch.get("section"), ch["chunk_index"], ch["text"]),
                )
                ids.append(cur.lastrowid)
                self.db.execute(
                    "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)",
                    (cur.lastrowid, ch["text"]),
                )
            self.db.commit()
            self.index.add_with_ids(vectors, np.array(ids, dtype="int64"))
            self._persist_index()

    def delete_document(self, doc_id: int) -> bool:
        """Remove a document: vectors from FAISS, rows from SQLite + FTS."""
        with self._lock:
            doc_row = self.db.execute(
                "SELECT id, filename FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if doc_row is None:
                return False
            ids = [
                r["id"]
                for r in self.db.execute(
                    "SELECT id FROM chunks WHERE doc_id = ?", (doc_id,)
                ).fetchall()
            ]
            if ids and self.index is not None:
                self.index.remove_ids(np.array(ids, dtype="int64"))
                self._persist_index()
            self.db.executemany(
                "DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in ids]
            )
            fname = doc_row["filename"] if "filename" in doc_row.keys() else None
            self.db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            self.db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            self.db.commit()
            still_used = bool(fname and self.db.execute(
                "SELECT 1 FROM documents WHERE filename = ? LIMIT 1", (fname,)
            ).fetchone())
        # Delete the original too: keeping a contract on disk after the user
        # deleted it defeats the point of deleting it.
        if fname and not still_used:
            (self.upload_dir / fname).unlink(missing_ok=True)
        return True

    # ── reads ──
    def list_documents(self) -> list[dict]:
        rows = self._reader_db().execute(
            """SELECT d.id, d.name, d.filename, d.created_at, d.meta_json,
                      COUNT(c.id) AS chunk_count
               FROM documents d LEFT JOIN chunks c ON c.doc_id = d.id
               GROUP BY d.id ORDER BY d.id DESC"""
        ).fetchall()
        titles = self.document_titles()
        others = self.counterparties()
        docs = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(d.pop("meta_json") or "null")
            d["title"] = titles.get(d["id"], d["name"])
            d["counterparty"] = others.get(d["id"], "")
            d["kind"] = document_kind(d["meta"])
            addr = (d["meta"] or {}).get("address") or {}
            d["city"] = addr.get("city") or ""
            d["state"] = (addr.get("state") or "").upper()
            d["zip"] = str(addr.get("zip") or "")
            d["renewal"] = renewal_view(d["meta"])
            d["review"] = review_flags(d["meta"], d["kind"])
            docs.append(d)
        return docs

    def get_document(self, doc_id: int) -> dict | None:
        row = self._reader_db().execute(
            "SELECT id, name, filename FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None

    def find_by_hash(self, file_hash: str) -> dict | None:
        row = self._reader_db().execute(
            "SELECT id, name, filename FROM documents WHERE file_hash = ?",
            (file_hash,),
        ).fetchone()
        return dict(row) if row else None

    def doc_ids(self) -> list[int]:
        return [r["id"] for r in self._reader_db().execute(
            "SELECT id FROM documents"
        ).fetchall()]

    def common_party(self, threshold: float = 0.5) -> str | None:
        """The party appearing on most contracts — i.e. the user's own company.

        In a portfolio of near-identical agreements (the same operator leasing
        space from many different owners) that name is on every document and
        tells you nothing. Detecting it lets the UI show the *counterparty*,
        which is what actually distinguishes one contract from another. Returns
        None when no name is common enough to be confident."""
        rows = self._reader_db().execute(
            "SELECT meta_json FROM documents"
        ).fetchall()
        metas = [json.loads(r["meta_json"]) for r in rows if r["meta_json"]]
        if len(metas) < 3:
            return None
        counts: dict[str, int] = {}
        for m in metas:
            for p in {_short_party(x) for x in (m.get("parties") or [])
                      if isinstance(x, str) and x.strip()}:
                counts[p] = counts.get(p, 0) + 1
        if not counts:
            return None
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        name, n = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        # Either it is on most contracts, or it simply recurs far more than any
        # other name — the latter matters when the corpus also holds unrelated
        # one-off agreements that would otherwise dilute the share.
        if n >= 3 and (n >= len(metas) * threshold or n > 2 * runner_up):
            return name
        return None

    def counterparties(self) -> dict[int, str]:
        """{doc_id: the party that is not the user's own company}."""
        own = self.common_party()
        out: dict[int, str] = {}
        for r in self._reader_db().execute(
            "SELECT id, meta_json FROM documents"
        ):
            meta = json.loads(r["meta_json"]) if r["meta_json"] else None
            # An explicit counterparty from extraction wins (works with a single
            # document, before common_party has a portfolio to reason over).
            explicit = (meta or {}).get("counterparty")
            if isinstance(explicit, str) and explicit.strip():
                out[r["id"]] = _short_party(explicit)
                continue
            parties = [_short_party(p) for p in ((meta or {}).get("parties") or [])
                       if isinstance(p, str) and p.strip()]
            drop = {own} if own else set()
            drop |= {p for p in parties
                     if any(op in p.lower() for op in _KNOWN_OPERATORS)}
            others = [p for p in parties if p not in drop] or parties
            out[r["id"]] = " & ".join(others[:2])
        return out

    def document_text(self, doc_id: int, limit: int = 60000) -> str:
        """Reassemble a document from its stored chunks — lets metadata be
        re-extracted without re-parsing the file or re-computing embeddings."""
        rows = self._reader_db().execute(
            "SELECT text FROM chunks WHERE doc_id = ? ORDER BY id", (doc_id,)
        ).fetchall()
        return "\n".join(r["text"] for r in rows)[:limit]

    def document_titles(self) -> dict[int, str]:
        """{doc_id: display title}, guaranteed unique. Two files of the same
        contract (a PDF and its text) would otherwise render identically, so
        collisions are disambiguated by file format, then by a counter."""
        rows = self._reader_db().execute(
            "SELECT id, name, filename, meta_json FROM documents"
        ).fetchall()
        titles: dict[int, str] = {}
        for r in rows:
            meta = json.loads(r["meta_json"]) if r["meta_json"] else None
            titles[r["id"]] = document_title(r["name"], meta)

        by_title: dict[str, list] = {}
        for r in rows:
            by_title.setdefault(titles[r["id"]], []).append(r)
        for base, group in by_title.items():
            if len(group) < 2:
                continue
            for n, r in enumerate(group, start=1):
                suffix = r["filename"].rsplit(".", 1)[-1].upper()
                candidate = f"{base} ({suffix})"
                if sum(1 for x in group
                       if x["filename"].rsplit(".", 1)[-1].upper() == suffix) > 1:
                    candidate = f"{base} ({suffix} {n})"
                titles[r["id"]] = candidate
        return titles

    def _chunk_row(self, chunk_id: int) -> dict | None:
        row = self._reader_db().execute(
            """SELECT c.id, c.text, c.page, c.section, c.chunk_index,
                      d.id AS doc_id, d.name AS doc_name, d.filename
               FROM chunks c JOIN documents d ON d.id = c.doc_id
               WHERE c.id = ?""",
            (chunk_id,),
        ).fetchone()
        return dict(row) if row else None

    def _chunk_ids_for(self, doc_ids: "Iterable[int]") -> list[int]:
        ids = list(doc_ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return [r["id"] for r in self._reader_db().execute(
            f"SELECT id FROM chunks WHERE doc_id IN ({marks})", ids)]

    def _vector_ranked_ids(self, query_vec: np.ndarray, fetch: int,
                           allowed_chunks: list[int] | None = None) -> list[int]:
        if self.index is None or self.index.ntotal == 0:
            return []
        params = None
        if allowed_chunks is not None:
            if not allowed_chunks:
                return []
            # Filter inside the search. Post-filtering a global top-N silently
            # returns nothing once the corpus dwarfs the selection.
            params = faiss.SearchParameters()
            params.sel = faiss.IDSelectorBatch(
                np.array(allowed_chunks, dtype="int64")
            )
        # FAISS releases the GIL, so a concurrent add_with_ids/remove_ids can
        # reallocate the very buffers being read. Share the writers' lock.
        with self._lock:
            n = min(fetch, self.index.ntotal)
            _, ids = self.index.search(query_vec.reshape(1, -1), n, params=params)
        return [int(i) for i in ids[0] if i != -1]

    def _keyword_ranked_ids(self, query_text: str, fetch: int,
                            doc_ids: "Iterable[int] | None" = None) -> list[int]:
        tokens = re.findall(r"[A-Za-z0-9]+", query_text)
        if not tokens:
            return []
        # Quote each token: a bare OR (Oregon!) or AND would be parsed as an
        # FTS5 operator and throw, silently disabling keyword search entirely.
        match = " OR ".join(f'"{t}"' for t in tokens)
        sql = ("SELECT f.rowid AS rowid FROM chunks_fts f "
               "WHERE f.chunks_fts MATCH ? ")
        args: list = [match]
        if doc_ids is not None:
            ids = list(doc_ids)
            if not ids:
                return []
            marks = ",".join("?" * len(ids))
            sql = ("SELECT f.rowid AS rowid FROM chunks_fts f "
                   "JOIN chunks c ON c.id = f.rowid "
                   f"WHERE f.chunks_fts MATCH ? AND c.doc_id IN ({marks}) ")
            args += ids
        sql += "ORDER BY bm25(f.chunks_fts) LIMIT ?"
        args.append(fetch)
        try:
            rows = self._reader_db().execute(sql, args).fetchall()
        except sqlite3.OperationalError:  # exotic query syntax — vector-only
            return []
        return [r["rowid"] for r in rows]

    def search(
        self,
        query_vec: np.ndarray,
        k: int,
        doc_ids: "Iterable[int] | None" = None,
        query_text: str | None = None,
    ) -> list[dict]:
        """Hybrid search: reciprocal-rank fusion of vector and BM25 rankings.
        Pass query_text=None for vector-only (used by coverage retrieval).
        doc_ids restricts the search to a subset of documents (user scope)."""
        allowed = set(doc_ids) if doc_ids is not None else None
        fetch = max(k * 6, 30)  # over-fetch so ranking fusion has candidates
        allowed_chunks = (
            self._chunk_ids_for(allowed) if allowed is not None else None
        )
        rankings = [self._vector_ranked_ids(query_vec, fetch, allowed_chunks)]
        if query_text:
            rankings.append(self._keyword_ranked_ids(query_text, fetch, allowed))

        scores: dict[int, float] = {}
        for ranking in rankings:
            for rank, cid in enumerate(ranking):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)

        results = []
        for cid in sorted(scores, key=scores.get, reverse=True):
            row = self._chunk_row(cid)
            if row is None:
                continue
            if allowed is not None and row["doc_id"] not in allowed:
                continue
            row["score"] = round(scores[cid], 4)
            results.append(row)
            if len(results) >= k:
                break
        return results

    def get_chunk_context(self, chunk_id: int, window: int = 2) -> dict | None:
        """Return a chunk plus its neighbours within the same document, in
        reading order, so a citation can be shown with surrounding context.
        Chunks of one document are inserted consecutively, so ids are
        contiguous within a document and ordering by id == reading order."""
        target = self._chunk_row(chunk_id)
        if target is None:
            return None
        rows = self._reader_db().execute(
            """SELECT id, page, section, text FROM chunks
               WHERE doc_id = ? AND id BETWEEN ? AND ?
               ORDER BY id""",
            (target["doc_id"], chunk_id - window, chunk_id + window),
        ).fetchall()
        return {
            "doc_id": target["doc_id"],
            "doc_name": target["doc_name"],
            "doc_title": self.document_titles().get(
                target["doc_id"], target["doc_name"]
            ),
            "filename": target["filename"],
            "page": target["page"],
            "section": target["section"],
            "target_id": chunk_id,
            "context": [
                {"id": r["id"], "page": r["page"], "section": r["section"],
                 "text": r["text"], "is_target": r["id"] == chunk_id}
                for r in rows
            ],
        }

    # ── geocode cache (an address does not move) ──

    def get_geocodes(self, keys: list[str]) -> dict[str, tuple[float, float]]:
        if not keys:
            return {}
        marks = ",".join("?" * len(keys))
        return {r["q"]: (r["lat"], r["lon"]) for r in self._reader_db().execute(
            f"SELECT q, lat, lon FROM geocache WHERE q IN ({marks})", keys)}

    def put_geocodes(self, items: dict[str, tuple[float, float]]) -> None:
        with self._lock:
            self.db.executemany(
                "INSERT INTO geocache (q, lat, lon) VALUES (?,?,?) "
                "ON CONFLICT(q) DO UPDATE SET lat=excluded.lat, lon=excluded.lon",
                [(k, v[0], v[1]) for k, v in items.items()],
            )
            self.db.commit()

    # ── chats (server-side history; incognito chats are never sent here) ──

    def list_chats(self) -> list[dict]:
        rows = self._reader_db().execute(
            "SELECT id, title, ts FROM chats ORDER BY ts DESC"
        )
        return [dict(r) for r in rows]

    def get_chat(self, chat_id: str) -> dict | None:
        r = self._reader_db().execute(
            "SELECT id, title, ts, msgs_json FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        if r is None:
            return None
        return {"id": r["id"], "title": r["title"], "ts": r["ts"],
                "msgs": json.loads(r["msgs_json"])}

    def upsert_chat(self, chat_id: str, title: str, ts: int, msgs: list) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO chats (id, title, ts, msgs_json) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, ts=excluded.ts, msgs_json=excluded.msgs_json",
                (chat_id, title, ts, json.dumps(msgs)),
            )
            self.db.commit()

    def delete_chat(self, chat_id: str) -> bool:
        with self._lock:
            cur = self.db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            self.db.commit()
            return cur.rowcount > 0


store = Store()
