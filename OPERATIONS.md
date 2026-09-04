# Contract knowledge system — operating runbook

This runbook covers a single-host deployment with a persistent data directory.
It turns the access, retention, backup, rollback, and retrieval-quality gates in
`DELIVERY_AND_READINESS.md` into operating steps.

## Deployment boundary

```text
reviewer browser → HTTPS / identity boundary → FastAPI application
                                              │
                         ┌────────────────────┴───────────────────┐
                         ▼                                        ▼
             persistent DATA_DIR                      configured model endpoint
       SQLite + FAISS + uploaded files             local Ollama or approved host
```

- Set `APP_PASSWORD` whenever the service is reachable beyond localhost.
- Terminate TLS at an approved reverse proxy or identity-aware tunnel.
- Keep `DATA_DIR` on encrypted storage with access limited to the service owner.
- Set `COOKIE_SECURE=1` behind HTTPS. Treat the built-in password as a
  single-team access gate; use an external identity layer for named users,
  roles, or document-level permissions.
- Keep model and embedding endpoints explicit in `.env`; do not inherit an
  unreviewed hosted endpoint.
- Allow URL ingestion only through `app/fetch_url.py`, which preflights
  credentials, ports, resolved addresses, redirects, size, and type. Enforce an
  outbound firewall or proxy rule that blocks private and link-local networks as
  the connection-level backstop.

## Pre-release checks

1. Confirm the approved corpus owner, users, use cases, retention window, and
   escalation owner.
2. Confirm the model-processing boundary and whether metadata extraction may use
   a hosted endpoint.
3. Run the focused tests:

   ```bash
   .venv/bin/python -m unittest discover -s tests -v
   ```

4. Rebuild and run the locked retrieval evaluation:

   ```bash
   ./eval/run_public_eval.sh
   ```

5. Exercise the static reviewer path and automated accessibility scan:

   ```bash
   npm ci
   npx playwright install chromium
   npm run test:browser
   ```

6. Run the isolated storage/retrieval reliability gate after persistence,
   indexing, or concurrency changes:

   ```bash
   .venv/bin/python benchmarking/run_reliability_evidence.py
   ```

7. Review every miss by category. Do not release a retrieval change merely
   because aggregate document recall remains high.
8. Review `SECURITY_THREAT_MODEL.md`, including every residual deployment risk.
9. Complete the deployment-specific answer-correctness, abstention, access,
   deletion, backup, restore, and rollback scenarios.

## Start and smoke test

Local operation:

```bash
cp .env.example .env
./run.sh
```

Container operation:

```bash
docker build -t contract-knowledge-system:release .
docker run --name contract-knowledge-system \
  --env-file .env \
  -p 8090:8090 \
  -v contract-rag-data:/app/data \
  contract-knowledge-system:release
```

Smoke-test the operating workflow:

- authentication is required when `APP_PASSWORD` is set;
- the approved document inventory and chunk counts load;
- a known exact-term question and a paraphrased question reach their expected
  passages;
- an unsupported question abstains;
- citation preview, source drawer, and original-file navigation agree;
- a temporary test document can be added and deleted without orphan chunks; and
- application startup reports no chunk/vector inconsistency warning.

Probe process and storage readiness separately:

```bash
curl -fsS http://localhost:8090/health/live
curl -fsS http://localhost:8090/health/ready
```

`/health/ready` returns 503 when SQLite, FTS, and FAISS are not mutually
consistent. Do not route retrieval traffic to an unready instance.

## Observability boundary

The application emits one-line JSON events for request completion, authentication
refusal, ingestion acceptance/completion/failure, upload rejection, duplicate
content, and readiness checks. Events carry a request ID, route template, status,
duration, safe reason/error type, and opaque artifact references where needed.

Questions, answers, document text, chunks, filenames, URLs, credentials, tokens,
cookies, addresses, emails, and phone numbers are not intended log fields and are
redacted by the event layer. Configure the reverse proxy and model provider to
the same standard; application filtering cannot govern their logs.

The current local retrieval-tier reference run used 500 fictional documents,
2,000 chunks, 1,000 searches, and 25 workers. It recorded zero exceptions,
1,000 / 1,000 expected-document top-1 results, 46.12 ms p95 latency, and 674.97
searches/second. Treat these as a reproducible single-machine baseline, not an
end-to-end answer SLO: OCR, network, embedding, and model generation are outside
that harness. Re-establish the baseline on the deployment host before setting
alerts or capacity limits.

## Backup and restore

The SQLite store, FAISS index, and uploaded source files form one recovery unit.
Stop writes before copying them so the snapshot remains internally consistent.

```bash
# Service stopped; choose an explicit backup directory for the release.
mkdir -p backups/contract-rag-release
cp -a data/. backups/contract-rag-release/
sha256sum backups/contract-rag-release/store.db \
          backups/contract-rag-release/faiss.index
```

Restore procedure:

1. Stop the application.
2. Preserve the failed data directory for incident review.
3. Replace `DATA_DIR` with the selected complete snapshot.
4. Start the application and confirm document, chunk, and vector counts.
5. Run the known-question, unsupported-question, citation, and deletion smoke
   checks before returning access.

If the FAISS index is corrupt but the source inventory is sound, rebuild the
index from the approved documents rather than treating keyword-only recovery as
the new production state.

The exercised application-level failure paths and their exact boundaries are in
`FAILURE_RECOVERY.md`.

## Application rollback

- Tag or retain the last accepted application image and its matching dependency
  lock.
- Back up `DATA_DIR` before a schema, chunking, embedding, or metadata change.
- Roll application code and data back together when the change alters stored
  structure or vector compatibility.
- A model or embedding change requires a fresh index and a new locked evaluation
  result; do not attach a new model to an old vector index.

## Retention and deletion

The business document owner sets the retention period. The operator records the
approved period for original files, derived chunks/embeddings, saved chats,
evaluation logs, and backups before launch.

- Application deletion removes the document row, chunks, FTS entries, FAISS
  vectors, and uploaded file.
- Backup expiration remains a separate operational responsibility; deleting a
  live document does not erase an older approved recovery snapshot.
- Access and incident logs should avoid document text and follow the approved
  security-log retention policy.

## Retrieval miss and feedback triage

Classify each reported issue before changing prompts or tuning retrieval:

| Failure class | First check | Owner response |
|---|---|---|
| Source absent or stale | approved corpus inventory | business owner corrects the source set |
| Extraction/OCR miss | original page versus stored text | operator reprocesses and verifies the page |
| Document miss | dense and keyword candidates | engineering adds a locked label and reviews retrieval |
| Passage miss | chunk boundary and rank fusion | engineering adjusts chunking/retrieval and reruns the set |
| Citation mismatch | answer annotation versus retrieved chunk | engineering fixes citation mapping before release |
| Answer error with correct support | answer text versus cited clause | reviewer corrects; engineering adds answer-level acceptance coverage |
| Unsupported completion | missing evidence versus response | release owner treats as a stop condition for the affected use case |

Record the question, expected source, failure class, disposition, owner, and
verification result. Promote recurring issues into the locked acceptance set so
the same failure cannot return silently.

## Shutdown

Revoke reviewer access, stop public ingress, stop the application, take the
required final snapshot, expire temporary credentials, and apply the approved
retention schedule to source files, derived data, logs, and backups.
