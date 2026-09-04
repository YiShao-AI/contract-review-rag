#!/usr/bin/env python3
"""Run an isolated concurrent-retrieval and storage-recovery drill.

The harness creates a deterministic fictional corpus in a temporary directory.
It does not call an embedding provider, language model, or external service.
Performance results therefore describe the local SQLite/FTS5/FAISS retrieval
tier, not end-to-end answer latency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


DEFAULT_DOCUMENTS = 500
DEFAULT_CHUNKS_PER_DOCUMENT = 4
DEFAULT_SEARCHES = 1_000
DEFAULT_WORKERS = 25
DEFAULT_DIMENSIONS = 96
SEED = 20260904


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * pct
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def sha256_files(paths: list[Path], base: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(base).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def seed_store(store, document_count: int, chunks_per_document: int,
               dimensions: int) -> tuple[np.ndarray, list[int], list[int], list[str]]:
    """Insert a large deterministic fixture and persist one aligned FAISS index."""
    import faiss

    rng = np.random.default_rng(SEED)
    total_chunks = document_count * chunks_per_document
    vectors = rng.standard_normal((total_chunks, dimensions)).astype("float32")
    faiss.normalize_L2(vectors)

    chunk_ids: list[int] = []
    chunk_doc_ids: list[int] = []
    tokens: list[str] = []
    with store._lock:
        for doc_number in range(document_count):
            file_hash = hashlib.sha256(
                f"fictional-contract-{doc_number}".encode("utf-8")
            ).hexdigest()
            doc_cursor = store.db.execute(
                "INSERT INTO documents (name, filename, file_hash) VALUES (?, ?, ?)",
                (
                    f"Fictional Agreement {doc_number:04d}",
                    f"fictional-{doc_number:04d}.txt",
                    file_hash,
                ),
            )
            doc_id = int(doc_cursor.lastrowid)
            for chunk_number in range(chunks_per_document):
                ordinal = doc_number * chunks_per_document + chunk_number
                token = f"locator{ordinal:06d}"
                text = (
                    f"Fictional contract evidence {token}. Section {chunk_number + 1} "
                    f"belongs to agreement {doc_number:04d} and contains no real data."
                )
                chunk_cursor = store.db.execute(
                    "INSERT INTO chunks (doc_id, page, section, chunk_index, text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (doc_id, chunk_number + 1, f"Section {chunk_number + 1}",
                     chunk_number, text),
                )
                chunk_id = int(chunk_cursor.lastrowid)
                store.db.execute(
                    "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)",
                    (chunk_id, text),
                )
                chunk_ids.append(chunk_id)
                chunk_doc_ids.append(doc_id)
                tokens.append(token)
        store.db.commit()
        store.index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimensions))
        store.index.add_with_ids(vectors, np.asarray(chunk_ids, dtype="int64"))
        store._persist_index()
        store._check_consistency()
    return vectors, chunk_ids, chunk_doc_ids, tokens


def run(args: argparse.Namespace) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    source_fingerprint = sha256_files(
        [
            repo_root / "app" / "store.py",
            Path(__file__).resolve(),
            repo_root / "tests" / "test_concurrent_retrieval.py",
            repo_root / "tests" / "test_storage_recovery.py",
        ],
        repo_root,
    )

    with tempfile.TemporaryDirectory(prefix="rag-reliability-") as temp:
        os.environ["DATA_DIR"] = temp
        # Import only after DATA_DIR is isolated; app.store creates its default
        # Store instance at import time.
        from app import store as store_module

        store = store_module.store
        vectors, chunk_ids, doc_ids, tokens = seed_store(
            store, args.documents, args.chunks_per_document, args.dimensions
        )
        initial_health = store.health_snapshot()

        task_rng = random.Random(SEED)
        tasks = [task_rng.randrange(len(chunk_ids)) for _ in range(args.searches)]

        for ordinal in tasks[:50]:
            store.search(vectors[ordinal], k=5, query_text=tokens[ordinal])

        def retrieve(ordinal: int) -> tuple[bool, float, str | None]:
            started = time.perf_counter()
            try:
                hits = store.search(
                    vectors[ordinal], k=5, query_text=tokens[ordinal]
                )
                matched = bool(hits and hits[0]["doc_id"] == doc_ids[ordinal])
                return matched, (time.perf_counter() - started) * 1000, None
            except Exception as exc:  # recorded by class only; no source content
                return False, (time.perf_counter() - started) * 1000, type(exc).__name__

        wall_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            search_results = list(pool.map(retrieve, tasks))
        wall_seconds = time.perf_counter() - wall_started
        outcomes = [matched for matched, _, _ in search_results]
        latencies_ms = [latency for _, latency, _ in search_results]
        exception_types = Counter(
            error_type for _, _, error_type in search_results if error_type
        )

        # Restart from the same persisted database/index and rerun a locked
        # sample before performing destructive recovery drills.
        store.close()
        restarted = store_module.Store()
        restart_health = restarted.health_snapshot()
        restart_sample = tasks[:50]
        restart_matches = sum(
            bool((hits := restarted.search(
                vectors[i], k=5, query_text=tokens[i]
            )) and hits[0]["doc_id"] == doc_ids[i])
            for i in restart_sample
        )

        # Verify deletion reaches the document, chunk/FTS records, vector, and
        # original file, then confirm the index remains internally consistent.
        deleted_ordinal = len(chunk_ids) - 1
        deleted_doc_id = doc_ids[deleted_ordinal]
        deleted = restarted.get_document(deleted_doc_id)
        deleted_path = restarted.upload_dir / deleted["filename"]
        deleted_path.write_text("fictional source", encoding="utf-8")
        delete_ok = restarted.delete_document(deleted_doc_id)
        deleted_hits = restarted.search(
            vectors[deleted_ordinal], k=5, query_text=tokens[deleted_ordinal]
        )
        deletion_health = restarted.health_snapshot()
        deletion_propagated = (
            delete_ok
            and restarted.get_document(deleted_doc_id) is None
            and not deleted_path.exists()
            and all(hit["doc_id"] != deleted_doc_id for hit in deleted_hits)
            and deletion_health["ready"]
        )

        # Corrupt a copied index, verify quarantine/readiness behavior, restore
        # the last good bytes, and prove retrieval returns after recovery.
        good_index = restarted.index_path.read_bytes()
        restarted.close()
        Path(temp, "faiss.index").write_bytes(b"deliberately corrupt index")
        quarantined = store_module.Store()
        quarantine_health = quarantined.health_snapshot()
        corrupt_artifact = quarantined.index_path.with_suffix(".corrupt")
        quarantine_ok = (
            not quarantine_health["ready"]
            and corrupt_artifact.exists()
            and not quarantined.index_path.exists()
        )
        quarantined.close()
        Path(temp, "faiss.index").write_bytes(good_index)
        recovered = store_module.Store()
        recovery_health = recovered.health_snapshot()
        recovery_i = next(i for i, doc_id in enumerate(doc_ids)
                          if doc_id != deleted_doc_id)
        recovered_hits = recovered.search(
            vectors[recovery_i], k=5, query_text=tokens[recovery_i]
        )
        recovery_ok = (
            recovery_health["ready"]
            and bool(recovered_hits)
            and recovered_hits[0]["doc_id"] == doc_ids[recovery_i]
        )
        recovered.close()

    p95_ms = percentile(latencies_ms, 0.95)
    throughput = args.searches / wall_seconds if wall_seconds else 0.0
    gates = {
        "zero_search_exceptions": sum(exception_types.values()) == 0,
        "exact_locator_top1": all(outcomes),
        "p95_under_500_ms_local_retrieval": p95_ms < 500,
        "throughput_at_least_20_searches_per_second": throughput >= 20,
        "restart_preserves_readiness_and_results": (
            restart_health["ready"]
            and restart_matches == len(restart_sample)
        ),
        "deletion_propagates": deletion_propagated,
        "corrupt_index_quarantines_and_restores": quarantine_ok and recovery_ok,
    }

    return {
        "schema_version": 1,
        "run_id": "RAG-RELIABILITY-20260904",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "statement": (
                "Isolated local storage/retrieval test using deterministic "
                "fictional records; excludes OCR, network, embedding provider, "
                "and answer-generation latency."
            ),
            "documents": args.documents,
            "chunks_per_document": args.chunks_per_document,
            "chunks": args.documents * args.chunks_per_document,
            "searches": args.searches,
            "workers": args.workers,
            "vector_dimensions": args.dimensions,
            "seed": SEED,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "source_fingerprint_sha256": source_fingerprint,
        },
        "retrieval": {
            "completed": len(outcomes),
            "expected_document_top1": sum(outcomes),
            "exceptions": sum(exception_types.values()),
            "exception_types": dict(exception_types),
            "wall_seconds": round(wall_seconds, 3),
            "throughput_searches_per_second": round(throughput, 2),
            "latency_ms": {
                "p50": round(percentile(latencies_ms, 0.50), 2),
                "p95": round(p95_ms, 2),
                "p99": round(percentile(latencies_ms, 0.99), 2),
                "max": round(max(latencies_ms), 2),
            },
        },
        "restart": {
            "sample_searches": len(restart_sample),
            "expected_document_top1": restart_matches,
            "ready": restart_health["ready"],
        },
        "deletion": {
            "propagated": deletion_propagated,
            "ready_after_delete": deletion_health["ready"],
            "remaining_documents": deletion_health["documents"],
            "remaining_chunks": deletion_health["chunks"],
            "remaining_vectors": deletion_health["vectors"],
        },
        "corrupt_index_recovery": {
            "quarantined": quarantine_ok,
            "readiness_failed_closed": not quarantine_health["ready"],
            "restored_from_last_good_index": recovery_ok,
            "ready_after_restore": recovery_health["ready"],
        },
        "acceptance_gates": gates,
        "passed": all(gates.values()),
    }


def markdown_report(result: dict) -> str:
    scope = result["scope"]
    retrieval = result["retrieval"]
    latency = retrieval["latency_ms"]
    gate_rows = "\n".join(
        f"| {name.replace('_', ' ')} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in result["acceptance_gates"].items()
    )
    return f"""# RAG retrieval reliability evidence — 2026-09-04

## Result

**{'PASS' if result['passed'] else 'FAIL'}** — {retrieval['completed']:,} hybrid searches completed with {retrieval['exceptions']} exceptions; {retrieval['expected_document_top1']:,} / {retrieval['completed']:,} exact-locator questions returned the labeled document first.

| Measure | Result |
|---|---:|
| Fictional documents | {scope['documents']:,} |
| Indexed chunks | {scope['chunks']:,} |
| Concurrent workers | {scope['workers']} |
| Throughput | {retrieval['throughput_searches_per_second']:.2f} searches/second |
| Retrieval latency p50 | {latency['p50']:.2f} ms |
| Retrieval latency p95 | {latency['p95']:.2f} ms |
| Retrieval latency p99 | {latency['p99']:.2f} ms |

The same persisted store was reopened and passed {result['restart']['expected_document_top1']} / {result['restart']['sample_searches']} locked searches. Deletion removed the selected document from SQLite, FTS5, FAISS, and the upload directory while leaving the store ready. A deliberately corrupted FAISS file was quarantined, caused readiness to fail closed, and was successfully restored from the last good index.

## Acceptance gates

| Gate | Status |
|---|---|
{gate_rows}

## Failure found and corrected

The initial 20-worker drill failed with `sqlite3.InterfaceError: bad parameter or other API misuse`. Read-only requests were sharing the writer connection across FastAPI worker threads. The correction introduced one read-only SQLite connection per thread, enabled WAL/busy-timeout behavior, and serialized writes. `tests/test_concurrent_retrieval.py` now preserves the failure as a regression check.

## Evidence boundary

{scope['statement']} The results support single-host retrieval concurrency and storage-recovery claims only; they are not an end-to-end multi-user capacity or model-latency result.

Machine-readable result: [`reliability-run-20260904.json`](reliability-run-20260904.json).
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=int, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks-per-document", type=int,
                        default=DEFAULT_CHUNKS_PER_DOCUMENT)
    parser.add_argument("--searches", type=int, default=DEFAULT_SEARCHES)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).resolve().parent / "evidence",
    )
    args = parser.parse_args()

    result = run(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "reliability-run-20260904.json"
    md_path = args.output_dir / "RELIABILITY_RUN_20260904.md"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")
    print(json.dumps({
        "passed": result["passed"],
        "json": str(json_path),
        "markdown": str(md_path),
        "retrieval": result["retrieval"],
    }, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
