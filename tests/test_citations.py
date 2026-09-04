"""Unit tests for citation annotation (app.rag._annotate).

Pure logic, no network: maps the bracketed labels a model emits back onto the
retrieved chunks, replacing each with a numbered marker and reporting the
citation order behind it. Run:

    .venv/bin/python tests/test_citations.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import _annotate  # noqa: E402


def hit(cid, title, page=None, section=None, score=1.0):
    return {"id": cid, "doc_id": cid, "doc_name": f"file_{cid}",
            "doc_title": title, "page": page, "section": section,
            "score": score, "text": ""}


HITS = [
    hit(1, "Vendor Supply Agreement — Ironclad & Quartz", page=2),
    hit(2, "Master Services Agreement — Summit & Cedar", section="3. TERM AND RENEWAL"),
    hit(3, "Master Services Agreement — Swiss Towers & Sunrise (PDF)", page=31),
    hit(4, "Master Services Agreement — Swiss Towers & Sunrise (TXT)",
        section="17.3", score=0.9),
    hit(5, "Polysilicon Supply Contract — Trina & GCL", score=0.8),
    hit(6, "Polysilicon Supply Contract — Trina & GCL", score=0.5),
]

CASES = [
    ("single label with page",
     "Warranty is 18 months [Vendor Supply Agreement — Ironclad & Quartz, p.2].",
     "Warranty is 18 months ⟦1⟧.", [1]),

    ("numbering follows order of first appearance",
     "A [Master Services Agreement — Summit & Cedar, § 3. TERM AND RENEWAL] "
     "and B [Vendor Supply Agreement — Ironclad & Quartz, p.2].",
     "A ⟦1⟧ and B ⟦2⟧.", [2, 1]),

    ("repeated citation reuses its number",
     "X [Vendor Supply Agreement — Ironclad & Quartz, p.2] "
     "and Y [Vendor Supply Agreement — Ironclad & Quartz, p.2].",
     "X ⟦1⟧ and Y ⟦1⟧.", [1]),

    ("two citations packed into one bracket, semicolon separated",
     "Longest [Master Services Agreement — Swiss Towers & Sunrise (PDF), p.31; "
     "Master Services Agreement — Swiss Towers & Sunrise (TXT), § 17.3–17.4].",
     "Longest ⟦1⟧⟦2⟧.", [3, 4]),

    ("titles differing only by format suffix must not cross-match",
     "See [Master Services Agreement — Swiss Towers & Sunrise (TXT), § 17.3].",
     "See ⟦1⟧.", [4]),

    ("bare document name credits that document's best chunk only",
     "Nothing on duration [Polysilicon Supply Contract — Trina & GCL].",
     "Nothing on duration ⟦1⟧.", [5]),

    ("unknown document is left as written, others still numbered",
     "See [Some Other Contract, p.9] and [Vendor Supply Agreement — Ironclad & Quartz, p.2].",
     "See [Some Other Contract, p.9] and ⟦1⟧.", [1]),

    ("no labels at all leaves text alone and lists every hit",
     "I could not find that in the provided documents.",
     "I could not find that in the provided documents.", [1, 2, 3, 4, 5, 6]),
]

failed = 0
for name, answer, want_text, want_ids in CASES:
    got_text, got_ids = _annotate(answer, HITS)
    ok = got_text == want_text and got_ids == want_ids
    failed += not ok
    print(f"{'OK  ' if ok else 'FAIL'}  {name}")
    if not ok:
        if got_text != want_text:
            print(f"        text: want {want_text!r}\n              got  {got_text!r}")
        if got_ids != want_ids:
            print(f"        ids:  want {want_ids}, got {got_ids}")

print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
if failed:
    raise AssertionError(f"{failed} citation annotation case(s) failed")
if __name__ == "__main__":
    sys.exit(0)
