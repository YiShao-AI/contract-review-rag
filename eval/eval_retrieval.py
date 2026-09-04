"""Retrieval evaluation over a locked, labeled question set.

Measures, per question:
  doc-hit    — is the expected document among the retrieved chunks?
  phrase-hit — does the retrieved text contain the expected key phrase?

No answer generation is involved; the run isolates document and passage
retrieval. Run from the repository root after building the public evaluation
index with ``eval/run_public_eval.sh``:

    .venv/bin/python eval/eval_retrieval.py --json-out eval/results.local.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import _retrieve  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument(
    "--json-out",
    type=Path,
    help="write per-question and aggregate results to this path",
)
args = parser.parse_args()

questions_path = Path(__file__).parent / "questions.json"
questions = json.loads(questions_path.read_text())

doc_hits = phrase_hits = 0
results = []
for index, q in enumerate(questions, start=1):
    hits = _retrieve(q["question"], None)
    docs = {h["doc_name"] for h in hits}
    text = " ".join(h["text"] for h in hits).lower()
    dh = q["expected_doc"] in docs
    ph = q["expected_phrase"].lower() in text
    doc_hits += dh
    phrase_hits += ph
    status = "OK  " if (dh and ph) else ("MISS-DOC " if not dh else "MISS-PHRASE ")
    print(f"{status:<12}{q['question']}")
    results.append(
        {
            "id": q.get("id", f"Q{index:02d}"),
            "category": q.get("category"),
            "document_hit": bool(dh),
            "passage_hit": bool(ph),
        }
    )

n = len(questions)
print(f"\ndoc-hit: {doc_hits}/{n} ({100*doc_hits//n}%)   "
      f"phrase-hit: {phrase_hits}/{n} ({100*phrase_hits//n}%)")

if args.json_out:
    payload = {
        "evaluation": "retrieval_only",
        "question_set": questions_path.name,
        "manifest": "manifest.json",
        "aggregate": {
            "questions": n,
            "document_hits": doc_hits,
            "passage_hits": phrase_hits,
        },
        "results": results,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2) + "\n")
