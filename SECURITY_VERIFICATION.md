# Security verification record

## Recorded result

| Check | Version | 2026-09-04 result |
|---|---:|---|
| Gitleaks working-tree scan | 8.30.1 | no secrets detected |
| Trivy dependency scan | 0.74.0 | 0 HIGH/CRITICAL findings requiring an available fix in pinned Python dependencies; the scan uses `ignore-unfixed: true` |
| Trivy configuration scan | 0.74.0 | 0 HIGH/CRITICAL Dockerfile findings |
| Focused security regressions | project suite | upload, URL import, prompt boundary, redaction, safe telemetry, deletion, and provider-failure checks passed |
| Workflow static validation | actionlint 1.7.12 | both GitHub Actions workflows passed |

The first Trivy configuration pass identified that the container ran as root.
The Dockerfile now creates an unprivileged application account, assigns the
application and data directory to it, and switches to that identity before the
server starts. The repeated scan returned no HIGH or CRITICAL finding.

## Continuous checks

`.github/workflows/security.yml` runs on pushes, pull requests, manual dispatch,
and a weekly schedule. It includes CodeQL for Python and JavaScript, a full-history
Gitleaks scan, and Trivy dependency, secret, and configuration scanning. Third-
party actions are pinned to immutable commit SHAs. Dependabot covers Python, npm,
and GitHub Actions dependencies.

The verification workflow separately runs the 31 focused tests, fictional-corpus
hash validation, the isolated reliability gate, browser interaction/accessibility
checks, and a release-container build.

## Reproduce locally

Run the application checks:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python benchmarking/run_reliability_evidence.py
npm ci && npm run test:browser
```

Run Gitleaks and Trivy 0.74.0 against the repository root using their documented
`dir` and `fs` commands. The CI definitions are the authoritative shared command
record; local binaries are intentionally not committed.

## Boundary

These checks verify the committed implementation and common repository risks.
They are not a penetration test and do not replace deployment-specific identity,
network egress, secret management, malware scanning, or provider-policy review.
