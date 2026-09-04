# RAG retrieval reliability evidence — 2026-09-04

## Result

**PASS** — 1,000 hybrid searches completed with 0 exceptions; 1,000 / 1,000 exact-locator questions returned the labeled document first.

| Measure | Result |
|---|---:|
| Fictional documents | 500 |
| Indexed chunks | 2,000 |
| Concurrent workers | 25 |
| Throughput | 674.97 searches/second |
| Retrieval latency p50 | 36.04 ms |
| Retrieval latency p95 | 46.12 ms |
| Retrieval latency p99 | 69.13 ms |

The same persisted store was reopened and passed 50 / 50 locked searches. Deletion removed the selected document from SQLite, FTS5, FAISS, and the upload directory while leaving the store ready. A deliberately corrupted FAISS file was quarantined, caused readiness to fail closed, and was successfully restored from the last good index.

## Acceptance gates

| Gate | Status |
|---|---|
| zero search exceptions | PASS |
| exact locator top1 | PASS |
| p95 under 500 ms local retrieval | PASS |
| throughput at least 20 searches per second | PASS |
| restart preserves readiness and results | PASS |
| deletion propagates | PASS |
| corrupt index quarantines and restores | PASS |

## Failure found and corrected

The initial 20-worker drill failed with `sqlite3.InterfaceError: bad parameter or other API misuse`. Read-only requests were sharing the writer connection across FastAPI worker threads. The correction introduced one read-only SQLite connection per thread, enabled WAL/busy-timeout behavior, and serialized writes. `tests/test_concurrent_retrieval.py` now preserves the failure as a regression check.

## Evidence boundary

Isolated local storage/retrieval test using deterministic fictional records; excludes OCR, network, embedding provider, and answer-generation latency. The results support single-host retrieval concurrency and storage-recovery claims only; they are not an end-to-end multi-user capacity or model-latency result.

Machine-readable result: [`reliability-run-20260904.json`](reliability-run-20260904.json).
