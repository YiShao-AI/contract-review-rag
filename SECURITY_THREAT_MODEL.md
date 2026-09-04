# Contract knowledge system — security threat model

## Scope and trust boundary

This implementation is shaped for a protected, single-team deployment. A
browser reaches FastAPI through an HTTPS or identity-aware boundary; source
files, extracted text, SQLite records, and the FAISS index remain in the
configured data directory; inference is either local or sent to an explicitly
configured compatible endpoint.

The built-in shared password is a deployment gate, not enterprise identity or
authorization. A multi-team deployment would require SSO, named identities,
role and document permissions, and retrieval-time authorization before any
source text is assembled for a model.

## Threat-to-control map

| Asset | Threat and attack path | Implemented safeguard | Verification | Residual risk / operating requirement |
|---|---|---|---|---|
| Contract corpus | A user imports a URL that resolves to loopback, private, or link-local infrastructure | Credentials and nonstandard ports are rejected; every DNS result and redirect is revalidated; response size and type are bounded | `tests/test_fetch_url.py` | DNS can change between validation and connection. Production egress policy must independently block private and metadata networks. |
| Parser host | A mislabeled, encrypted, malformed, or pathologically compressed upload exhausts or confuses a parser | Extension allowlist, total upload cap, PDF signature check, DOCX package/entry/expanded-size/compression checks, and binary-TXT rejection run before extraction | `tests/test_operational_controls.py` | No malware scanner is bundled. Higher-trust deployments should scan uploads and isolate parsing workers. |
| Model instruction boundary | A contract contains text such as “ignore prior instructions” or requests disclosure | Retrieved excerpts are explicitly labeled and delimited as untrusted data; answer and metadata prompts prohibit following document commands; answers remain source-linked | prompt-boundary regression in `tests/test_operational_controls.py` | Instruction separation reduces exposure but is not a proof against every model behavior. High-consequence uses need a locked adversarial set and human approval. |
| Tenant and document access | One user retrieves another user's documents | The protected single-team deployment can require a shared password | authentication smoke check and deployment checklist | There is no per-user, per-document, or tenant authorization. Do not use the current access model for mutually isolated groups. |
| Financial identifiers | Bank or routing numbers enter embeddings or a hosted metadata request | Deterministic masking occurs before both embeddings and remote-capable metadata extraction | `tests/test_ingest_privacy.py` | Other sensitive fields require a corpus-specific policy; provider retention and processing terms remain a deployment decision. |
| Logs | Questions, answers, filenames, document text, credentials, or URLs become a second sensitive corpus | Structured events allowlisted by purpose; sensitive field names are redacted; request IDs, route templates, status, duration, safe event codes, and opaque references are retained | telemetry regressions in `tests/test_operational_controls.py` | Reverse-proxy and provider logs have separate configurations and retention policies. |
| Provider failure response | A model exception exposes an endpoint, credential-bearing detail, or internal stack information to the browser | The answer stream retains retrieved sources, emits a stable retryable error code, and logs only the exception class with the request ID | provider-failure regression in `tests/test_operational_controls.py` | Provider availability remains external; the single-host implementation does not queue answer requests for later replay. |
| Stored and derived data | Deleting a document leaves searchable chunks, FTS rows, vectors, or the uploaded file | One deletion path removes the source file, document row, chunks, FTS entries, and vector entries | deletion-propagation test in `tests/test_storage_recovery.py` | Approved backups follow their own expiration schedule; deletion from a live store does not rewrite historical recovery media. |
| Retrieval index | An interrupted or corrupt FAISS write silently serves an incomplete corpus | Index writes use a temporary file and atomic replace; unreadable indexes are quarantined; readiness reconciles chunk, FTS, and vector counts | recovery drills in `tests/test_storage_recovery.py`; `/health/ready` | A mismatched non-empty corpus must be rebuilt before serving retrieval. SQLite and FAISS still form a coordinated single-host recovery unit. |
| Session cookie | A network observer or script captures the shared session | Cookie is HTTP-only and SameSite=Lax; `COOKIE_SECURE=1` is available and required behind HTTPS | configuration inspection and HTTPS deployment checklist | Sessions are in process memory and are not named-user identities. Rotation, revocation, idle expiry, and centralized access review require an external identity layer. |
| Secrets | API keys or the shared password enter source control | Runtime configuration is environment-based and `.env` is excluded from version control | repository secret scan and release checklist | A managed deployment should inject secrets from its platform secret manager and rotate them outside the application. |

## Security release decisions

Before broader deployment, the owner must decide and record:

1. approved corpus, users, and high-consequence questions;
2. identity and document-authorization model;
3. local versus hosted model boundary and provider retention terms;
4. source, derived-data, log, and backup retention periods;
5. network egress and upload-scanning controls; and
6. escalation and incident owners.

The current controls make these boundaries visible and testable. They do not
substitute for the organization-specific decisions above.
