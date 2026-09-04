# Public retrieval evaluation

This folder contains the inputs, runner, and recorded output for the contract
retrieval check. It evaluates retrieval only: whether each question reaches the
expected agreement and the labeled supporting passage. Generated-answer
correctness is deliberately evaluated separately.

## Included evidence

- `corpus/` — 30 fictional agreements in PDF, DOCX, and TXT formats;
- `corpus.sha256` — a content manifest for the locked source set;
- `questions.json` — 22 labeled retrieval questions;
- `manifest.json` — model and retrieval settings for the recorded run;
- `results.json` — per-question and aggregate outcomes from that run; and
- `build_eval_index.py` / `eval_retrieval.py` — the executable ingestion and
  evaluation path.

## Reproduce the check

The default configuration expects Ollama with `nomic-embed-text` available at
`http://localhost:11434/v1`.

```bash
ollama pull nomic-embed-text
./eval/run_public_eval.sh
```

The script creates a clean index under `.eval-data`, ingests the committed
corpus through the application pipeline, runs all labeled questions, and writes
`eval/results.local.json`. With the same embedding-model artifact, the aggregate
and per-question booleans should match `results.json`.

The committed result is a locked baseline, not a claim about generated-answer
accuracy. Unit tests separately cover citation mapping, precise source spans,
clause boundaries, identifier masking, and URL-import preflight controls;
keyboard activation and the exercised source-drawer accessibility state are
verified by the Playwright suite under `tests/browser/`.
