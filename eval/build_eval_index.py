"""Build a fresh retrieval index from the committed fictional corpus."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingest import ingest_file


parser = argparse.ArgumentParser()
parser.add_argument(
    "--corpus",
    type=Path,
    default=Path(__file__).parent / "corpus",
)
args = parser.parse_args()

files = sorted(
    path
    for path in args.corpus.iterdir()
    if path.suffix.lower() in {".pdf", ".docx", ".txt"}
)
if not files:
    raise SystemExit(f"No supported evaluation files found in {args.corpus}")

failures = []
for path in files:
    try:
        # This check isolates retrieval. Structured metadata extraction is an
        # answer-path concern and would add a second model dependency here.
        ingest_file(path, path.stem, include_metadata=False)
        print(f"OK   {path.name}")
    except Exception as exc:
        failures.append((path.name, str(exc)))
        print(f"FAIL {path.name}: {exc}")

print(f"\nIndexed {len(files) - len(failures)} of {len(files)} documents")
if failures:
    raise SystemExit(1)
