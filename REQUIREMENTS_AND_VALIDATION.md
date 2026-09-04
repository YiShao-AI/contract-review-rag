# Contract-Review RAG requirements and validation

This document translates the operating need into testable requirements and
connects each requirement to the implemented workflow and available evidence.

The professional implementation used this architecture for internal customer
support. The requirements below define the public contract-review use case over
fictional agreements; its stakeholder roles are the intended operating owners
and approval points for that use case.

## Business decision

The system supports a user answering:

> Which contract language applies to this operating question, what source
> supports the answer, and is the evidence sufficient to act?

The definition of done is a verified answer, a correction, or an informed
escalation. Fluent generated text without inspectable support is not completion.

## Stakeholders

| Stakeholder | Need | Success signal |
|---|---|---|
| Operations or contract reviewer | answer recurring contract questions without reopening and rereading every agreement | shorter verified lookup with fewer file-by-file searches |
| Business owner or manager | understand upcoming renewals, obligations, and portfolio comparisons | actionable dates and terms remain linked to source clauses |
| Legal or subject-matter reviewer | inspect the original language before a consequential action | answer, passage, page/section, and original file remain connected |
| System administrator | control where documents and model processing occur | local-first configuration, bounded uploads, deletion, and explicit provider settings |

The discovery inputs, user stories, delivery decisions, roles, data-readiness
gates, risk register, and launch checklist are recorded in
[`DELIVERY_AND_READINESS.md`](DELIVERY_AND_READINESS.md).

## Current and target workflow

```text
HISTORICAL
question → guess filename/keywords → open files → search or read → interpret
         → calculate if needed → ask an expert when uncertain

SYSTEM WORKFLOW
question → hybrid retrieval → grounded answer → focused evidence preview
         → surrounding clause/original file → act, correct, or escalate

KNOWLEDGE PIPELINE
PDF/DOCX/TXT/scan → extract or OCR → redact protected identifiers
                  → clause-aware chunks → vector + keyword indexes
                  → retrieval with document/page/section metadata
```

## Functional requirements

| ID | Priority | User need | Acceptance criterion | Evidence state | Implementation evidence |
|---|---|---|---|---|---|
| FR-01 | Must | Ask in ordinary business language | Paraphrased questions retrieve relevant documents without requiring exact clause wording. | evaluated | dense-vector retrieval in `app/rag.py` and locked question set |
| FR-02 | Must | Preserve exact terms and identifiers | Names, percentages, dates, amounts, and clause language remain searchable through an exact-term path. | evaluated | SQLite FTS5, rank fusion, and passage labels |
| FR-03 | Must | Handle mixed contract files | PDF, DOCX, and TXT ingest; scanned pages and filled-form overlays enter OCR. | implemented; inspected | `app/ingest.py` and committed mixed-format corpus |
| FR-04 | Must | Verify the answer | Every displayed citation maps to a retrieved chunk with document, page/section, and original-file context. | tested | citation objects, annotation checks, chunk endpoint, and source drawer |
| FR-05 | Must | Show precise support | Preview and drawer highlight the smallest useful supporting sentence or field rather than the entire chunk. | unit tested | `_citation_selection`, `highlights`, and source-range rendering |
| FR-06 | Should | Compare the portfolio | Users can ask ranked or cross-document questions over structured contract fields. | demonstrated | structured and superlative answer paths |
| FR-07 | Should | Calculate actionable dates | Renewal and notice terms can produce a labeled deadline while retaining the clauses used. | demonstrated | metadata validation and renewal calculation |
| FR-08 | Must | Handle unsupported questions | When the corpus does not support the requested fact, the system states that it was not found rather than inventing it. | demonstrated | abstention response path and unanswered-question walkthrough |
| FR-09 | Must | Keep the corpus current | New uploads follow the same extraction, metadata, chunking, indexing, and source-link process. | implemented; inspected | ingestion API and index persistence |
| FR-10 | Must | Remove a document cleanly | Deletion removes the document, chunks, and uploaded file without leaving retrievable orphan content. | implemented; inspected | document-delete workflow in `app/main.py` and `app/store.py` |

## Non-functional and governance requirements

| ID | Priority | Requirement | Acceptance criterion | Evidence state |
|---|---|---|---|---|
| NFR-01 | Must | Processing boundary | Local inference is available; a hosted endpoint is enabled only through explicit configuration. | implemented; inspected |
| NFR-02 | Must | Sensitive identifier handling | Bank account and routing values are masked before embedding and before any remote-capable metadata extraction. | unit tested |
| NFR-03 | Must | Upload safety | Only supported extensions enter ingestion, filenames do not collide, and direct upload size is bounded. | implemented; inspected |
| NFR-04 | Must | Source traceability | Document identity and structural metadata survive every stage from extraction to display. | evaluated and tested |
| NFR-05 | Must | Accessibility | Citation markers support pointer hover, keyboard focus, Enter/Space activation, and readable source navigation. | implemented; preview behavior unit tested |
| NFR-06 | Must | Recoverability | Persisted indexes can be rebuilt and corrupt index state does not silently become authoritative. | implemented; inspected |
| NFR-07 | Must | Evaluation repeatability | Retrieval questions, corpus, hashes, settings, results, and a clean-index runner are committed. | reproducibility assets verified |
| NFR-08 | Must | URL import boundary | Preflight accepts only HTTP(S) targets resolving to public addresses on standard ports, revalidates redirects, and retains size/type limits; deployment egress policy provides the network backstop. | unit tested; egress policy is a deployment gate |
| NFR-09 | Must | Concurrent retrieval | Parallel reads do not share a SQLite connection; writes remain serialized and index reads cannot overlap index mutation. | regression tested and load tested |
| NFR-10 | Must | Provider failure behavior | If answer generation fails after retrieval, sources remain available and the client receives a stable retryable error without infrastructure detail. | fault-injection tested |

## Data inventory and ownership

| Data | Source | Owner | Treatment |
|---|---|---|---|
| Original agreement | uploaded business document | document owner | retained as the authoritative source and opened from citations |
| Extracted/OCR text | ingestion pipeline | knowledge-system operator | stored with document and structural metadata; rebuilt when the source is reingested |
| Chunk and embedding | derived from source | knowledge-system operator | rebuilt from the source when the index changes |
| Contract metadata | extracted and validated fields | business reviewer | used for filtering, comparison, and deadline calculations; source remains available |
| Chat question and answer | user interaction | application user | stored according to the configured operating mode; incognito path avoids saved chat history |
| Evaluation labels | public validation set | implementation owner | kept separate from runtime answers and rerun after retrieval changes |

## Acceptance scenarios and evidence status

These scenarios define business-readable acceptance behavior. The evidence
column distinguishes automated checks, static demonstrations, and inspected
implementation paths; none is labeled as signed business UAT without a user
acceptance record.

| ID | Scenario | Expected result | Evidence class | Current evidence |
|---|---|---|---|---|
| UAT-01 | Ask for a site address in plain language. | Answer names the site and address; citation preview contains the address; source drawer highlights the address only. | automated + static demonstration | precise-address unit test and walkthrough |
| UAT-02 | Ask for a commission rate. | Answer returns the rate and basis; source highlights the exact percentage-and-fee phrase. | automated + static demonstration | commission-preview unit test and walkthrough |
| UAT-03 | Ask for a notice contact stored in separated form fields. | Answer returns the contact; source highlights name and email as separate evidence spans. | automated | non-adjacent-field unit test |
| UAT-04 | Ask for a termination notice period. | Answer returns the period and calculated date; source highlights the decisive notice phrase. | automated + static demonstration | notice-highlight unit test and walkthrough |
| UAT-05 | Ask which agreement has the highest commission rate. | System compares recorded rates, identifies the highest, and cites that agreement. | static demonstration | structured cross-document walkthrough |
| UAT-06 | Upload a scanned or filled-form agreement. | OCR recovers visible values missing from the ordinary text layer and retains source context. | implementation inspection | ingestion and OCR paths |
| UAT-07 | Ask for information not contained in the corpus. | System says the information was not found and does not state an unsupported fact. | static demonstration | unanswered-question walkthrough |
| UAT-08 | Process text containing bank/routing numbers with a remote-capable metadata mode. | Masked text, not the original identifier, reaches metadata extraction. | automated | privacy regression test |
| UAT-09 | Navigate citations without a mouse. | Citation can receive focus and open with Enter or Space. | automated browser check | Playwright keyboard focus, Enter activation, source-drawer, and exact-mark assertions in `tests/browser/static-demo.spec.js` |

## Current evaluation results

| Check | Result | Interpretation |
|---|---:|---|
| Expected document retrieved | 22 / 22 | All labeled questions reached the intended agreement. |
| Expected supporting passage retrieved | 20 / 22 | The retrieval path reached the labeled operative language in 20 cases. |
| Citation annotation resolved | 8 / 8 | Answer labels mapped to their intended retrieved chunks. |
| Focused citation behaviors | 6 / 6 | Address, commission, contact, notice, hover preview, and clause boundaries behaved as specified. |
| Pre-extraction masking | pass | Remote-capable metadata input received redacted identifiers. |
| Concurrent hybrid retrieval | 1,000 / 1,000 | Exact-locator searches returned the expected document first with no exceptions through 25 workers. |
| Retrieval latency | 46.12 ms p95 | Local SQLite/FTS5/FAISS tier over 2,000 deterministic fictional chunks; excludes model and network time. |
| Restart and recovery drill | pass | Reopen, deletion propagation, corrupt-index quarantine, and last-good-index restoration behaved as specified. |

These checks isolate different failure modes: document selection, passage
selection, citation-to-evidence mapping, focused display, and processing-boundary
behavior. They should remain separate rather than being collapsed into a single
accuracy number.

The fictional source corpus, hashes, labeled questions, settings manifest,
per-question results, and clean-index runner are committed in [`eval/`](eval/README.md).

## Traceable implementation map

- Ingestion and source structure: [`app/ingest.py`](app/ingest.py)
- Retrieval and answer routing: [`app/rag.py`](app/rag.py)
- Persistence and index behavior: [`app/store.py`](app/store.py)
- API workflows: [`app/main.py`](app/main.py)
- Source interaction and PDF viewer: [`static/index.html`](static/index.html)
- Labeled retrieval set: [`eval/questions.json`](eval/questions.json)
- Focused citation tests: [`tests/test_citation_previews.py`](tests/test_citation_previews.py)
- Citation annotation checks: [`tests/test_citations.py`](tests/test_citations.py)
- Processing-boundary test: [`tests/test_ingest_privacy.py`](tests/test_ingest_privacy.py)
- URL-import boundary tests: [`tests/test_fetch_url.py`](tests/test_fetch_url.py)
- Concurrent retrieval regression: [`tests/test_concurrent_retrieval.py`](tests/test_concurrent_retrieval.py)
- Reliability harness and result: [`benchmarking/`](benchmarking/README.md)
