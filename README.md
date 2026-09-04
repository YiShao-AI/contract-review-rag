# Contract-Review RAG

A local-first knowledge system for asking plain-English questions about a
contract portfolio and receiving answers connected to the exact supporting
language. It turns PDFs, DOCX files, scans, filled forms, and text agreements
into a searchable operating resource without requiring users to repeatedly open
and reread each document.

**Project site:** <https://yishao-ai.github.io/contract-review-rag/>

- [Interactive static walkthrough](https://yishao-ai.github.io/contract-review-rag/demo/)
- [Product and business-analysis notes](https://yishao-ai.github.io/contract-review-rag/workbook.html)
- [`REQUIREMENTS_AND_VALIDATION.md`](REQUIREMENTS_AND_VALIDATION.md)
- [`DELIVERY_AND_READINESS.md`](DELIVERY_AND_READINESS.md)
- [`OPERATIONS.md`](OPERATIONS.md)
- [`VALIDATION_RESULTS.md`](VALIDATION_RESULTS.md)
- [`SECURITY_THREAT_MODEL.md`](SECURITY_THREAT_MODEL.md)
- [`FAILURE_RECOVERY.md`](FAILURE_RECOVERY.md)

**Evidence boundary:** The professional system applied this retrieval pattern to
internal customer support. This public implementation applies the same
architecture to fictional agreements so document ingestion, hybrid retrieval,
citations, and source navigation can be inspected end to end.

## At a glance

| | |
|---|---|
| **Operating problem** | Contract status may be visible while revenue share, renewal language, notice contacts, deadlines, and exceptions remain buried in individual files. |
| **Target decision** | Which clause answers the question, what is the supporting passage, and is the evidence sufficient to act or escalate? |
| **Workflow change** | Ask in plain language, retrieve through vector and exact-term search, receive a grounded answer, and open the precise supporting text. |
| **My role** | Problem framing, requirements, data-readiness analysis, retrieval and citation design, implementation, evaluation, and workflow validation. |

## Core capabilities

- PDF, DOCX, and TXT ingestion, with OCR for scanned and filled-form pages;
- clause-aware chunks that keep section, page, document, and source identity;
- hybrid retrieval using FAISS dense vectors and SQLite FTS5 keyword search,
  fused with reciprocal-rank fusion;
- structured extraction for dates, parties, compensation, addresses, contacts,
  renewal terms, and notice periods;
- cross-document comparison and calculated notice deadlines;
- citations that resolve to the supporting chunk and original document context;
- focused citation previews and exact phrase highlighting rather than marking an
  entire retrieved chunk;
- masking of bank and routing numbers before embeddings or remote-capable
  metadata extraction; and
- bounded share-link ingestion with credential, port, resolved-address,
  redirect, size, and type preflight controls;
- file-structure and decompression limits before PDF, DOCX, or TXT parsing;
- privacy-safe structured events, request IDs, liveness, and index-consistency
  readiness checks; and
- local Ollama inference or a configurable hosted model endpoint.

## Retrieval path

```text
documents → extract / OCR → clause-aware chunks → vector + keyword indexes
          → hybrid retrieval → grounded answer → focused citation → original file
```

The interface keeps the answer, evidence preview, surrounding clause, and
original document connected. Hovering or focusing a citation opens a readable
preview; selecting it opens the source drawer and highlights only the decisive
phrase, such as an address, commission basis, contact field, or notice period.

## Requirements and traceability

| Requirement | Implementation | Verification |
|---|---|---|
| Handle paraphrase and exact contract language | FAISS + FTS5 + reciprocal-rank fusion in [`app/rag.py`](app/rag.py) | labeled retrieval evaluation |
| Preserve source identity | clause metadata and document links in [`app/ingest.py`](app/ingest.py) | citation annotation checks |
| Highlight the smallest useful support | citation-unit selection and phrase matching in [`app/rag.py`](app/rag.py) | [`tests/test_citation_previews.py`](tests/test_citation_previews.py) |
| Keep citations navigable and accessible | hover, focus, keyboard, source drawer, and PDF view in [`static/index.html`](static/index.html) | static walkthrough, source-span unit tests, and Playwright interaction/accessibility checks |
| Protect sensitive financial identifiers | pre-processing redaction in [`app/ingest.py`](app/ingest.py) | [`tests/test_ingest_privacy.py`](tests/test_ingest_privacy.py) |
| Treat document commands as untrusted data | prompt boundaries in [`app/rag.py`](app/rag.py) and [`app/ingest.py`](app/ingest.py) | [`tests/test_operational_controls.py`](tests/test_operational_controls.py) |
| Reject malformed and pathological uploads | pre-parser checks in [`app/main.py`](app/main.py) | [`tests/test_operational_controls.py`](tests/test_operational_controls.py) |
| Expose safe operational health | structured events and liveness/readiness endpoints | telemetry and storage-recovery regressions |
| Recover cleanly from partial index writes | atomic persistence, quarantine, count reconciliation | [`tests/test_storage_recovery.py`](tests/test_storage_recovery.py) |
| Decline unsupported completion | grounded prompt and abstention path | public unanswered-question walkthrough |

The full requirements matrix, current/future workflow, data ownership, UAT
scenarios, and evaluation interpretation are in
[`REQUIREMENTS_AND_VALIDATION.md`](REQUIREMENTS_AND_VALIDATION.md).

## Evaluation

The locked public contract set currently reports:

- **22 / 22** labeled questions retrieved the expected contract;
- **20 / 22** reached the expected supporting passage; and
- **8 / 8** citation-annotation checks resolved to the intended retrieved chunks.

The 30 fictional source files, content hashes, question labels, retrieval
settings, per-question results, and clean-index runner are committed under
[`eval/`](eval/README.md). This makes the published retrieval baseline
inspectable and rerunnable rather than relying on an unshared index.

The current focused-suite and evaluation record is in
[`VALIDATION_RESULTS.md`](VALIDATION_RESULTS.md).

The current **29 / 29** focused unit suite also verifies precise address, commission, contact, and
notice-period evidence; clause-sized chunking; hover-preview focus; separate
highlights for non-adjacent support fields; and masking before remote-capable
metadata extraction. It also exercises upload structure limits, untrusted-source
prompt separation, request correlation, safe telemetry, ingestion rollback,
deletion propagation, readiness, and vector-index recovery. URL-import checks
cover private and loopback targets, embedded credentials, nonstandard ports,
public DNS resolution, and redirects.

A separate Playwright check exercises the static review path in Chromium:
opening a saved answer, focusing a citation, reading its hover preview, opening
the source drawer by keyboard, and confirming that only the decisive phrase is
marked. The same state passes an automated axe WCAG A/AA scan.

## Run locally

```bash
cp .env.example .env
./run.sh
```

Open <http://localhost:8090>. The default configuration uses local Ollama.

Rebuild the fictional corpus index and evaluate retrieval:

```bash
./eval/run_public_eval.sh
```

Run the focused verification suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Run the browser interaction and accessibility checks:

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

## Implementation map

| Area | Primary files |
|---|---|
| Ingestion, OCR, redaction, and chunking | [`app/ingest.py`](app/ingest.py) |
| Retrieval, structured answers, citations, and abstention | [`app/rag.py`](app/rag.py) |
| Persistence and indexes | [`app/store.py`](app/store.py) |
| API and document workflows | [`app/main.py`](app/main.py) |
| Operational event boundary | [`app/telemetry.py`](app/telemetry.py) |
| User interface and source viewer | [`static/index.html`](static/index.html) |
| Public static demonstration | [`docs/demo/`](docs/demo/) |
| Browser interaction and accessibility checks | [`tests/browser/static-demo.spec.js`](tests/browser/static-demo.spec.js) |
| Evaluation set | [`eval/questions.json`](eval/questions.json) |
| Reproducible evaluation inputs and results | [`eval/`](eval/README.md) |
| Server-side URL import boundary | [`app/fetch_url.py`](app/fetch_url.py) and [`tests/test_fetch_url.py`](tests/test_fetch_url.py) |
| Security decisions and residual risks | [`SECURITY_THREAT_MODEL.md`](SECURITY_THREAT_MODEL.md) |
| Exercised recovery paths | [`FAILURE_RECOVERY.md`](FAILURE_RECOVERY.md) |

## Stack

FastAPI · FAISS · SQLite FTS5 · PDF.js · OCR · Ollama / configurable model API

## Data boundary

The public walkthrough uses non-confidential agreements with fictional parties,
terms, contacts, and values. It demonstrates the same ingestion, retrieval,
citation, and source-navigation pattern without including employer source code,
production contracts, credentials, or confidential records.
