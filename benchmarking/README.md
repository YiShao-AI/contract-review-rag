# Reliability evidence

`run_reliability_evidence.py` exercises the local persistence and hybrid
retrieval tier with a deterministic fictional corpus. It was added after an
exploratory concurrent run exposed a shared-SQLite-connection failure.

Run it from the repository root with the project virtual environment:

```bash
.venv/bin/python benchmarking/run_reliability_evidence.py
```

The default run creates 500 documents and 2,000 chunks, executes 1,000 hybrid
searches through 25 workers, restarts the store, tests deletion propagation,
and drills corrupt-index quarantine and restoration. All state is created under
a temporary directory. The harness makes no model, embedding, or network calls.

The generated Markdown and JSON under `benchmarking/evidence/` are committed so
the result can be reviewed without rerunning the test. The source fingerprint in
the JSON binds each result to the implementation, harness, and regression tests
used for that run.
