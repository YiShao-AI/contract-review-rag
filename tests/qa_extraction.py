"""QA: check extracted metadata against evidence in the contract text.

Extraction is an LLM guess; this re-derives what it can with regexes over the
stored text and reports disagreements. It is deliberately conservative — it
only judges fields it can find hard evidence for, so a "MISMATCH" is a real
problem and not a parsing artefact.

    .venv/bin/python tests/qa_extraction.py
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.store import store  # noqa: E402

MONTHS = ("January February March April May June July August September "
          "October November December").split()
_DATE = re.compile(
    r"(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s*(\d{4})")


def iso(m):
    return f"{m.group(3)}-{MONTHS.index(m.group(1))+1:02d}-{int(m.group(2)):02d}"


checks = Counter()
problems = []


def judge(doc, field, expected, actual, evidence=""):
    if expected is None:
        checks["no-evidence"] += 1
        return
    if actual is None:
        checks["missing"] += 1
        problems.append((doc, field, expected, "(missing)", evidence))
        return
    if str(expected).lower() == str(actual).lower():
        checks["match"] += 1
    else:
        checks["mismatch"] += 1
        problems.append((doc, field, expected, actual, evidence))


for d in store.list_documents():
    text = store.document_text(d["id"], 30000)
    m = d.get("meta") or {}
    addr = m.get("address") or {}
    contact = m.get("contact") or {}
    name = d.get("counterparty") or d["name"]

    # Term end: "Current Term <date> through <date>"
    term = re.search(r"Current Term[^\n]*through\s+" + _DATE.pattern, text)
    judge(name, "expiration_date",
          iso(re.search(_DATE, term.group(0)[term.group(0).lower().index("through"):]))
          if term else None,
          m.get("expiration_date"), term.group(0)[:70] if term else "")

    # Compensation: percentage or dollar amount on the Compensation line
    comp = re.search(r"Compensation[^\n]*", text)
    if comp:
        line = comp.group(0)
        pct = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        usd = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", line)
        judge(name, "compensation_model",
              "commission" if pct else ("fixed" if usd else None),
              m.get("compensation_model"), line[:70])
        if pct:
            judge(name, "commission_rate", f"{float(pct.group(1)):g}%",
                  m.get("commission_rate"), line[:70])

    zc = re.search(r"\b(\d{5})(?:-\d{4})?\b", text[:2500])
    judge(name, "address.zip", zc.group(1) if zc else None, addr.get("zip"),
          zc.group(0) if zc else "")

    ph = re.search(r"\b(\d{3}-\d{3}-\d{4})\b", text)
    judge(name, "contact.phone", ph.group(1) if ph else None,
          (contact.get("phone") or "").replace("(", "").replace(") ", "-"),
          ph.group(0) if ph else "")

    em = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    judge(name, "contact.email", em.group(0) if em else None,
          contact.get("email"), em.group(0) if em else "")

    nd = re.search(r"(\d{2,3})\s*days[^\n]{0,60}(?:notice|non-renewal|renewal)", text, re.I)
    judge(name, "notice_days", int(nd.group(1)) if nd else None,
          m.get("notice_days"), nd.group(0)[:60] if nd else "")

print("=== extraction QA ===")
for k in ("match", "mismatch", "missing", "no-evidence"):
    print(f"  {k:<12} {checks[k]}")
total = checks["match"] + checks["mismatch"] + checks["missing"]
if total:
    print(f"  accuracy on checkable fields: {100*checks['match']//total}%")

if problems:
    print(f"\n=== {len(problems)} disagreement(s) ===")
    by_field = Counter(p[1] for p in problems)
    for f, n in by_field.most_common():
        print(f"  {f}: {n}")
    print()
    for doc, field, exp, act, ev in problems[:14]:
        print(f"  {doc[:26]:<26} {field:<18} text={str(exp)[:22]:<24} extracted={str(act)[:22]}")
        if ev:
            print(f"    evidence: {ev[:96]}")
