# Contract knowledge system validation record

## Recorded checks

| Field | Value |
|---|---|
| Run date | 2026-09-04 |
| Runtime | Python 3.12.3 with the pinned project dependencies |
| Focused unit suite | 31 / 31 passed |
| Citation-annotation cases | 8 / 8 passed |
| Browser interaction checks | 2 / 2 passed in headless Chromium |
| Automated accessibility scan | 0 axe WCAG A/AA violations in the exercised source-drawer state |
| Fictional corpus integrity | 30 / 30 files matched `eval/corpus.sha256` |
| Retrieval baseline | 22 / 22 expected documents; 20 / 22 expected passages |
| Concurrent retrieval | 1,000 / 1,000 expected-document top-1; 0 exceptions through 25 workers |
| Local retrieval performance | 674.97 searches/second; 46.12 ms p95 over 2,000 fictional chunks |
| Storage recovery sequence | restart, deletion propagation, corrupt-index quarantine, and restore passed |

## Commands

Focused tests and annotation checks:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Static browser interaction and accessibility:

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

Corpus integrity:

```bash
sha256sum -c eval/corpus.sha256
```

Clean-index retrieval evaluation:

```bash
ollama pull nomic-embed-text
./eval/run_public_eval.sh
```

Isolated concurrent retrieval and recovery:

```bash
.venv/bin/python benchmarking/run_reliability_evidence.py
```

`run_public_eval.sh` fixes top-k, chunk size, overlap, and reranking settings,
rebuilds the index from the committed mixed-format corpus, and writes the same
schema as `eval/results.json` for direct comparison.

## Evidence by failure mode

| Failure mode | Evidence |
|---|---|
| Correct agreement is not retrieved | 22-question document-hit baseline |
| Correct agreement is retrieved but operative language is missed | per-question passage labels and two retained misses |
| Answer label resolves to the wrong retrieved chunk | 8 citation-annotation cases |
| Citation preview marks an entire chunk instead of decisive support | address, commission, contact, and notice-span unit tests |
| Numbered clauses merge into an imprecise source block | clause-boundary unit test |
| Protected identifiers reach embedding or remote-capable metadata input | pre-extraction masking unit test |
| Common unsafe share-link targets pass preflight | public-address, credential, port, and redirect unit tests |
| Malformed or pathologically compressed input reaches a document parser | PDF, DOCX, compression-ratio, and binary-TXT boundary tests |
| Retrieved document instructions are presented as model commands | explicit untrusted-data delimiter and prompt-policy test |
| Operational correlation requires logging private request content | request-ID and sensitive-field-redaction tests |
| Failed ingestion leaves a partial document | rollback fault-injection test |
| Deletion leaves source or derived records retrievable | file, document, chunk, FTS, and vector propagation test |
| Interrupted or corrupt vector-index writes silently replace a good index | atomic-write and quarantine recovery drills |
| Store/index mismatch serves as healthy | liveness and count-reconciling readiness checks |
| Concurrent readers corrupt or misuse one shared SQLite connection | thread-local-reader regression plus 1,000-search, 25-worker run |
| Answer provider exception exposes infrastructure detail or removes source access | safe retryable SSE error and source-preservation regression |
| Static citation flow requires a mouse or highlights the whole chunk | Playwright focus, Enter-key, drawer, and exact-mark assertions |
| Exercised static review state has detectable WCAG A/AA failures | axe scan after opening a saved answer and its source drawer |

The retrieval baseline intentionally retains its two passage misses so the
public result remains diagnostic. The load and recovery checks use deterministic
fictional records and exclude OCR, network, embedding-provider, and answer-model
latency; they support the stated single-host retrieval tier, not a production
availability claim. Generated-answer correctness, abstention, named-user
authorization, deployment-specific security controls, and business reviewer
acceptance remain separate release gates.
