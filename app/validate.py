"""Validation of LLM-extracted metadata.

Extraction is best-effort and occasionally confident about nonsense (a state
of "JS", a date in 1900). A value that is wrong is worse than one that is
missing: a bad expiry silently drops a contract out of every renewal filter,
whereas a missing one can be flagged and fixed. So implausible values are
discarded and recorded, and the document is marked for review.
"""
from __future__ import annotations

import re
from datetime import date

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","VI","GU","AS","MP",
}
MIN_YEAR, MAX_YEAR = 1990, 2100

# Fields a site/placement agreement should carry for the renewal workflow.
EXPECTED_SITE = ["expiration_date", "notice_days", "renewal_type", "address.state",
                 "address.city", "contact.name", "compensation_model"]


def _get(meta: dict, path: str):
    cur = meta
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _valid_date(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        d = date.fromisoformat(v.strip()[:10])
    except ValueError:
        return False
    return MIN_YEAR <= d.year <= MAX_YEAR


def validate(meta: dict | None) -> tuple[dict, list[str]]:
    """Return (cleaned metadata, list of rejected field paths)."""
    if not isinstance(meta, dict):
        return {}, []
    m = {k: v for k, v in meta.items()}
    rejected: list[str] = []

    def drop(path: str):
        rejected.append(path)
        parts = path.split(".")
        cur = m
        for p in parts[:-1]:
            cur = cur.get(p) if isinstance(cur.get(p), dict) else {}
        if isinstance(cur, dict):
            cur[parts[-1]] = None

    for f in ("effective_date", "expiration_date"):
        if m.get(f) is not None and not _valid_date(m[f]):
            drop(f)

    # An expiry before the start date means one of them was misread.
    if _valid_date(m.get("effective_date")) and _valid_date(m.get("expiration_date")):
        if date.fromisoformat(m["expiration_date"][:10]) <= date.fromisoformat(
            m["effective_date"][:10]
        ):
            drop("expiration_date")

    nd = m.get("notice_days")
    if isinstance(nd, str) and nd.strip().isdigit():   # "60" is a common output
        nd = m["notice_days"] = int(nd.strip())
    if nd is not None and not (isinstance(nd, (int, float)) and 0 <= nd <= 730):
        drop("notice_days")

    addr = m.get("address")
    if isinstance(addr, dict):
        st = addr.get("state")
        if st is not None:
            s = str(st).strip().upper()
            if s in US_STATES:
                addr["state"] = s
            else:
                drop("address.state")
        z = addr.get("zip")
        if z is not None:
            zs = re.sub(r"\D", "", str(z))
            if len(zs) in (5, 9):
                addr["zip"] = zs[:5]
            else:
                drop("address.zip")

    rate = m.get("commission_rate")
    if rate is not None:
        num = re.sub(r"[^0-9.]", "", str(rate))
        try:
            val = float(num)
            # A rate below 1 is almost certainly a fraction the model failed to
            # convert (0.175 for 17.5%); refuse it rather than be 100x wrong.
            if not (1 <= val <= 100):
                raise ValueError
            m["commission_rate"] = f"{val:g}%"
        except ValueError:
            drop("commission_rate")

    rt = m.get("renewal_type")
    if rt is not None:
        r = str(rt).strip().lower()
        if r in ("auto", "operator_option", "mutual", "none"):
            m["renewal_type"] = r
        else:
            drop("renewal_type")

    model = m.get("compensation_model")
    if model is not None and str(model).strip().lower() not in (
        "fixed", "commission", "revenue_share", "hybrid", "none"
    ):
        drop("compensation_model")
    elif isinstance(model, str):
        m["compensation_model"] = model.strip().lower()

    np_ = m.get("notice_party")
    if np_ is not None and str(np_).strip().lower() not in ("owner", "operator", "either"):
        drop("notice_party")
    elif isinstance(np_, str):
        m["notice_party"] = np_.strip().lower()

    mt = m.get("min_transactions_terminate")
    if isinstance(mt, str) and re.sub(r"\D", "", mt):
        mt = m["min_transactions_terminate"] = int(re.sub(r"\D", "", mt))
    if mt is not None and not (isinstance(mt, (int, float)) and 0 <= mt <= 100000):
        drop("min_transactions_terminate")

    return m, rejected


def review_flags(meta: dict | None, kind: str = "site") -> list[str]:
    """Fields a document of this kind should have but doesn't."""
    meta = meta or {}
    expected = EXPECTED_SITE if kind == "site" else ["expiration_date", "contact.name"]
    missing = [f for f in expected if _get(meta, f) in (None, "", [], {})]
    return missing + [f"rejected:{f}" for f in (meta.get("_rejected") or [])]
