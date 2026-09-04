# Contract knowledge system — discovery, decisions, and readiness

This record connects the operating problem to delivery choices and release
controls. The professional workflow used the retrieval pattern for internal
customer support; the public contract workflow is an inspectable implementation
over fictional agreements.

## Discovery synthesis

The requirements came from the recurring decisions users needed to make, the
source material available to answer them, and the conditions under which an
answer could be trusted.

| Operating signal | Pain point or constraint | Requirement derived | Confirmation path |
|---|---|---|---|
| Support questions repeated across tickets and calls | Useful resolutions remained dependent on an experienced agent's memory | Make prior resolutions searchable and keep the answer linked to its source | Agent retrieves and verifies within the established messaging workflow |
| Contract terms lived in PDFs, DOCX files, scans, and filled forms | File-by-file review was slow and ordinary extraction could miss visible form values | Support mixed formats, OCR, structural metadata, and original-file navigation | Ingestion checks plus source-view UAT scenarios |
| Percentages, dates, addresses, and notice language are consequential | Semantic similarity alone can miss exact terms; fluent prose cannot be the authority | Fuse vector and exact-term search, preserve citations, and abstain when support is missing | Locked retrieval set, citation checks, and unsupported-question scenario |
| Documents may contain financial identifiers | Embedding or hosted processing can cross a data boundary | Mask protected identifiers before embedding or remote-capable extraction; allow local inference | Privacy regression test and explicit provider configuration |
| Users need both a fast answer and enough context to act | Showing an entire chunk makes verification slow; showing too little can hide qualifications | Preview the decisive phrase, retain surrounding clause context, and open the original | Focused citation tests and static source walkthrough |

## User stories and acceptance

| ID | User story | Acceptance condition | Delivery state |
|---|---|---|---|
| US-01 | As a reviewer, I want to ask in ordinary language so I can find applicable terms without guessing contract wording. | A paraphrased question reaches the expected agreement and supporting passage. | Implemented; retrieval baseline recorded |
| US-02 | As a reviewer, I want every answer tied to source text so I can verify it before acting. | Citation opens the correct document context and highlights the decisive phrase. | Implemented; unit and walkthrough evidence |
| US-03 | As a manager, I want comparable fields and calculated dates so I can review a portfolio rather than one file at a time. | Structured fields retain their source and calculated dates identify the clauses used. | Implemented; scenario evidence |
| US-04 | As a subject-matter reviewer, I want unsupported questions to stop at “not found” so missing evidence does not become a business fact. | No unsupported completion is presented as an answer; the user can inspect or escalate. | Implemented; scenario evidence |
| US-05 | As a system administrator, I want explicit processing and deletion controls so the corpus remains governable. | Provider choice is configuration-controlled; deletion removes document, chunks, and file. | Implemented; code-path evidence |
| US-06 | As a keyboard user, I want source markers to be operable without a mouse. | Citation receives focus and opens with Enter or Space. | Implemented; Playwright interaction check and axe scan |

## Delivery decisions

| Decision | Business reason | Technical consequence |
|---|---|---|
| Treat source text as the authority | A generated answer is useful only when a person can verify the operative language | Answer objects retain document, page or section, chunk, and focused evidence spans |
| Use hybrid retrieval | Contract questions combine paraphrase with exact names, percentages, dates, and clause terms | FAISS dense candidates and SQLite FTS5 candidates are fused before answer generation |
| Keep local inference available | Document sensitivity and deployment constraints vary by organization | Ollama is the default; a hosted compatible endpoint requires explicit configuration |
| Separate retrieval, citation, and answer evaluation | A correct document hit can still contain the wrong passage or support a wrong answer | Results remain separate by failure mode instead of using one accuracy score |
| Keep answer verification in the workflow | Adoption falls when source review requires leaving the task and reopening files manually | Hover/focus preview, source drawer, surrounding clause, and original document stay connected |

## Roles and handoffs

| Role | Owns | Handoff or decision |
|---|---|---|
| Business or contract owner | authoritative document set, access, retention, and material interpretation | approves corpus scope and high-consequence use cases |
| Reviewer or operations user | question, evidence review, correction, and escalation | accepts, corrects, or routes the answer based on source text |
| Knowledge-system operator | ingestion, index health, provider configuration, deletion, and evaluation run | releases a corpus only after source and retrieval checks pass |
| Subject-matter or legal reviewer | interpretation of consequential clauses and exceptions | remains the approval point for actions requiring professional judgment |
| Engineering owner | application behavior, access boundary, observability, backup, and rollback | resolves technical defects and maintains the release controls |

## Data readiness gates

| Source or derived data | Readiness risk | Gate before use | Implemented control |
|---|---|---|---|
| Digital PDF, DOCX, and TXT | missing structural cues or malformed files | supported type, extractable text, source identity retained | format validation and clause-aware extraction |
| Scans and filled forms | values may exist only in the visual layer | OCR completes and decisive fields can be checked against the page | OCR fallback/overlay and original-page viewer |
| Extracted metadata | model output may omit or misclassify a field | null remains null; consequential values retain source access | validation, deterministic derivations, review flags |
| Chunks and embeddings | index can drift from the source store | chunk/vector counts reconcile or the index is rebuilt | consistency check and recoverable index load |
| Evaluation labels | tuning against the test set can inflate apparent quality | locked corpus and question hashes; results recorded per question | committed corpus manifest, labels, runner, and results |

## Risk and dependency register

| Risk or dependency | Owner | Control or response | Release gate |
|---|---|---|---|
| Source document is stale, duplicated, or outside approved scope | business owner | corpus inventory, source identity, deletion, and refresh process | approved source set and owner confirmed |
| OCR omits a filled value | system operator + reviewer | OCR overlay, source view, and human verification for consequential fields | sampled page-level check passes |
| Retrieval finds the contract but misses the operative passage | engineering owner | labeled passage checks, hybrid retrieval, and miss review by category | agreed passage threshold passes |
| Generated text overstates unsupported evidence | engineering owner + reviewer | grounded prompt, abstention, citation requirement, and human approval | unsupported-question and answer-level checks pass |
| Hosted processing would cross the approved data boundary | system administrator | local default, explicit provider setting, and pre-processing redaction | provider and retention settings approved |
| A server-side share link targets internal infrastructure | engineering owner | URL preflight, standard ports, redirect revalidation, size/type caps, and deployment egress policy | URL boundary regression passes; egress policy is a deployment gate |
| Uploaded content attacks a parser or model instruction boundary | engineering owner | pre-parser structure/decompression limits; explicit untrusted-data delimiters; source-linked review | upload and prompt-boundary regressions pass; malware scanning and adversarial acceptance set remain deployment gates |
| Operational logs expose source content | engineering owner + security owner | privacy-safe event schema, sensitive-key redaction, opaque references, and request correlation | telemetry regressions pass; proxy/provider log policy approved |
| Stored index is incomplete after an interrupted write | system operator + engineering owner | atomic index replace, corrupt-artifact quarantine, count-based readiness, and corpus rebuild procedure | storage recovery drills pass and readiness is healthy |
| Parallel requests contend for storage | engineering owner | WAL mode, one read connection per worker thread, serialized writes, and bounded busy timeout | concurrency regression and 1,000-search reliability run pass |
| Model provider fails after retrieval | system operator + engineering owner | retain retrieved sources, return a stable retryable error code, and emit a content-free correlated event | provider-outage regression passes |
| Access, deletion, backup, or rollback is undefined | system administrator | authenticated deployment, deletion workflow, index rebuild, and backup procedure | `OPERATIONS.md` defines the release procedure |

## Readiness checklist

| Gate | Evidence | State |
|---|---|---|
| Requirements are testable and traceable | `REQUIREMENTS_AND_VALIDATION.md` | complete for the public implementation |
| Fictional evaluation corpus and labels are reproducible | `eval/` manifest, source hashes, runner, and results | complete |
| Core citation, privacy, URL-import, upload, telemetry, concurrency, and recovery behaviors have regression coverage | 31 focused tests, 8 annotation checks, and the committed reliability run | complete for the stated single-team boundary |
| Static source-verification flow is keyboard-operable and passes an automated accessibility scan | 2 Playwright checks, including axe WCAG A/AA rules | complete for the exercised Chromium states |
| Business corpus owner, access, retention, and approved use cases are named | operating-owner sign-off | required for each enterprise deployment |
| End-to-end answer correctness and abstention thresholds are agreed | answer-level acceptance set | required before broader decision use |
| Feedback, miss triage, and rollback owners are assigned | `OPERATIONS.md` plus deployment owner assignment | required before broader rollout |

The final three gates are resolved during deployment planning. They connect a
technically successful retrieval pilot to accountable enterprise use.
