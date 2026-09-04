"""Spatial questions: "which site is nearest to X", "what is within 5 miles".

Measured behaviour of the provider models drives this split. Asked *where* a
place is, they are accurate to a few hundred feet and stable across repeats.
Asked *which is closest*, they guess — in testing the top answer was not even
in the top five once the arithmetic was done on the coordinates they had just
supplied. So the model geocodes and local code does every comparison.

Geocodes are cached: an address does not move.
"""
from __future__ import annotations

import json
import math
import re

from .providers import generate_answer
from .store import store

EARTH_MI = 3958.8

_SPATIAL = re.compile(
    r"\b(nearest|closest|near(?:by| to)?|next to|within\s+\d+\s*(?:mi|mile|miles|km)"
    r"|how far|distance (?:to|from|between)|driving distance|walking distance)\b",
    re.IGNORECASE,
)

_GEOCODE_PROMPT = (
    "Give approximate decimal-degree coordinates for each line. Reply ONLY as "
    'JSON mapping the exact input line to [latitude, longitude]: '
    '{"<line>": [38.1234, -77.1234]}. Omit any line you cannot place. No prose.'
)


def is_spatial(question: str) -> bool:
    return bool(_SPATIAL.search(question))


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * EARTH_MI * math.asin(math.sqrt(h))


def _ask_coords(lines: list[str]) -> dict[str, tuple[float, float]]:
    if not lines:
        return {}
    try:
        raw = generate_answer([
            {"role": "system", "content": _GEOCODE_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ])
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        return {}
    out = {}
    for k, v in (data.items() if isinstance(data, dict) else []):
        if (isinstance(v, (list, tuple)) and len(v) == 2
                and all(isinstance(x, (int, float)) for x in v)
                and -90 <= v[0] <= 90 and -180 <= v[1] <= 180):
            out[k] = (float(v[0]), float(v[1]))
    return out


def geocode(lines: list[str]) -> dict[str, tuple[float, float]]:
    """Cached geocoding. Only unseen lines cost a model call."""
    known = store.get_geocodes(lines)
    missing = [ln for ln in lines if ln not in known]
    if missing:
        fresh = _ask_coords(missing)
        if fresh:
            store.put_geocodes(fresh)
            known.update(fresh)
    return known


def address_line(meta: dict | None) -> str | None:
    a = (meta or {}).get("address") or {}
    parts = [a.get("street"), a.get("city"), a.get("state"), a.get("zip")]
    parts = [str(p).strip() for p in parts if p]
    return ", ".join(parts) if len(parts) >= 2 else None


def _landmark(question: str) -> str | None:
    """Ask what place the question is anchored on, rather than pattern-matching
    every phrasing of 'near'."""
    try:
        raw = generate_answer([
            {"role": "system", "content":
                "Extract the place the question measures distance from. Reply "
                'ONLY as JSON: {"place": string or null}. Return the MOST '
                "SPECIFIC place named — a station, building or intersection — "
                "never broadened to its city. Append the city and state for "
                'geocoding, e.g. "union station dc" -> "Union Station, '
                'Washington, DC"; "the capitol" -> "United States Capitol, '
                'Washington, DC". Use null only if no place is named.'},
            {"role": "user", "content": question},
        ])
        m = re.search(r"\{.*\}", raw, re.S)
        place = (json.loads(m.group(0)) if m else {}).get("place")
        return str(place).strip() or None if place else None
    except Exception:
        return None


def spatial_report(question: str, docs: list[dict]) -> dict | None:
    """Return {origin, ranked:[(miles, doc)], unplaced:[...]} or None."""
    place = _landmark(question)
    if not place:
        return None
    addressed = [(d, address_line(d.get("meta"))) for d in docs]
    lines = [ln for _, ln in addressed if ln]
    coords = geocode([place] + lines)
    origin = coords.get(place)
    if not origin:
        return None
    ranked, unplaced = [], []
    for d, ln in addressed:
        c = coords.get(ln) if ln else None
        if c:
            ranked.append((haversine(origin, c), d))
        else:
            unplaced.append(d)
    ranked.sort(key=lambda t: t[0])
    return {"place": place, "origin": origin, "ranked": ranked, "unplaced": unplaced}
