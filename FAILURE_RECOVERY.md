# Contract knowledge system — failure and recovery evidence

## Evidence boundary

These are isolated fault-injection checks against the current implementation,
not claims of production incidents or multi-node availability. They verify that
important single-host failures have an explicit outcome and recovery path.

## Exercised failure paths

| Injected condition | Expected behavior | Automated evidence |
|---|---|---|
| Chunk persistence fails after a document row is created | The partial document is rolled back instead of remaining as an unsearchable record | `test_failed_chunk_persistence_rolls_back_document_row` |
| FAISS serialization writes a partial temporary file and then raises | The last complete index remains byte-for-byte unchanged | `test_interrupted_index_write_preserves_last_good_index` |
| The saved FAISS index cannot be read at startup | The bad artifact is moved to `.corrupt`; the process can start and readiness reflects whether stored chunks still need an index rebuild | `test_corrupt_index_is_quarantined_and_nonempty_store_is_not_ready` |
| A document is deleted | Source file, document row, chunks, FTS rows, and vector entries are all removed | `test_delete_propagates_to_file_rows_fts_and_vectors` |
| Chunk, FTS, and vector counts diverge | `/health/ready` reports not ready rather than presenting the index as healthy | storage health logic and readiness regression |
| Background ingestion fails | The client receives a generic failure plus request reference; structured logs record the request ID and error type without the document or exception text | `test_failed_ingestion_returns_reference_not_exception_detail` and telemetry regressions |
| Concurrent retrieval shares one SQLite connection | Each worker receives its own read connection while writes remain serialized; parallel searches complete without connection misuse | `test_parallel_hybrid_searches_use_isolated_reader_connections` and the 1,000-search reliability run |
| The answer provider becomes unavailable after retrieval | Retrieved sources remain visible; the stream returns a safe, retryable error code and logs only the provider error class | `test_stream_preserves_sources_and_returns_safe_retryable_error` |

Run the drills with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Recorded on 2026-09-04: **31 / 31 tests passed**, followed by **8 / 8
citation-annotation checks**. The isolated reliability run also completed **1,000
/ 1,000** concurrent hybrid searches without an exception, then passed restart,
deletion, corrupt-index quarantine, and restore checks. Full measurements and
the machine-readable result are under [`benchmarking/evidence/`](benchmarking/evidence/).

## Operator response

- **Readiness fails after index loss:** stop retrieval traffic, preserve the
  failed artifact, rebuild from the approved source corpus, rerun the locked
  retrieval evaluation, then restore readiness.
- **Ingestion failure:** use the request ID to locate the safe structured event;
  correct the parser, storage, or model dependency; retry the source after
  confirming no partial document remains.
- **Answer provider unavailable:** keep the retrieved sources available, return
  the retryable `answer_provider_unavailable` code, inspect the correlated safe
  event, and retry after provider health recovers.
- **Corpus deletion:** confirm live document, chunk, FTS, vector, and file counts;
  then apply the separately approved backup-retention schedule.
- **Application regression:** restore the last accepted image together with its
  compatible data snapshot whenever schema, chunking, or embedding compatibility
  changed.

## Limits and next scale boundary

SQLite WAL, thread-local readers, a serialized writer, and in-process ingestion
are appropriate to this single-host workflow. The measured retrieval tier is
concurrent, but ingestion does not provide durable queueing or multi-worker
recovery. A larger deployment should move ingestion to a durable job system with
persisted states, idempotency, bounded retries, and dead-letter review. That is
a deliberate next architecture boundary rather than a capability claimed by
this repository.
