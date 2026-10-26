"""Match bills against the categories in config/categories.yml.

Each bill gets, per category, a confidence level:
  "match"     at least one strong term matched
  "possible"  only weak terms matched, alongside a context term
plus the list of terms that matched (shown in the app so you can see why a
bill was flagged) and any auto sub-tags.

Text inside an `exclude` pattern is blanked out before matching, so a passing
citation like "Voting Rights Act of 1965" cannot by itself flag a bill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES_PATH = ROOT / "config" / "categories.yml"

_DASHES = re.compile(r"[‐‑‒–—―−­]")
_QUOTES = re.compile(r"[‘’‚‛′]")
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = _DASHES.sub("-", text or "")
    text = _QUOTES.sub("'", text)
    text = text.replace(" ", " ")
    return _SPACE.sub(" ", text).lower().strip()


def _compile(patterns):
    out = []
    for p in patterns or []:
        out.append((p, re.compile(p, re.IGNORECASE)))
    return out


@dataclass
class Category:
    key: str
    name: str
    description: str
    strong: list
    weak: list
    context: list
    exclude: list
    subtags: dict = field(default_factory=dict)


def load_categories(path: Path = CATEGORIES_PATH) -> list[Category]:
    raw = yaml.safe_load(path.read_text())
    cats = []
    for key, c in raw["categories"].items():
        cats.append(
            Category(
                key=key,
                name=c.get("name", key),
                description=(c.get("description") or "").strip(),
                strong=_compile(c.get("strong")),
                weak=_compile(c.get("weak")),
                context=_compile(c.get("context")),
                exclude=_compile(c.get("exclude")),
                subtags={k: _compile(v) for k, v in (c.get("subtags") or {}).items()},
            )
        )
    return cats


def _blank(text: str, patterns) -> str:
    for _, rx in patterns:
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _hits(text: str, patterns, limit: int = 6):
    found = []
    for _, rx in patterns:
        m = rx.search(text)
        if m:
            found.append(m.group(0).strip())
            if len(found) >= limit:
                break
    return found


def classify_text(text: str, categories: list[Category], lead: str = "", allow_weak: bool = True) -> dict:
    """Return {category_key: {level, terms, subtags}} for categories that hit.

    Sub-tags (ban, adoption, ...) are read from `lead` (title and the start of
    the summary) when it yields any, because full bill text often mentions
    bans and adoptions in passing; otherwise from the whole text."""
    base = normalize(text)
    lead_n = normalize(lead)
    if not base:
        return {}
    results = {}
    for cat in categories:
        t = _blank(base, cat.exclude) if cat.exclude else base
        strong = _hits(t, cat.strong)
        level = None
        terms = strong
        if strong:
            level = "match"
        elif allow_weak:
            weak = _hits(t, cat.weak)
            if weak and any(rx.search(t) for _, rx in cat.context):
                level = "possible"
                terms = weak
        if not level:
            continue
        subtags = []
        if lead_n:
            tl = _blank(lead_n, cat.exclude) if cat.exclude else lead_n
            subtags = [name for name, pats in cat.subtags.items() if any(rx.search(tl) for _, rx in pats)]
        if not subtags:
            subtags = [name for name, pats in cat.subtags.items() if any(rx.search(t) for _, rx in pats)]
        results[cat.key] = {"level": level, "terms": sorted(set(terms)), "subtags": subtags}
    return results


def merge(a: dict, b: dict) -> dict:
    """Combine two classification results (e.g. title-based and full-text)."""
    out = {k: dict(v) for k, v in a.items()}
    for k, v in b.items():
        if k not in out:
            out[k] = dict(v)
            continue
        cur = out[k]
        if v["level"] == "match":
            cur["level"] = "match"
        cur["terms"] = sorted(set(cur["terms"]) | set(v["terms"]))
        cur["subtags"] = sorted(set(cur["subtags"]) | set(v["subtags"]))
    return out


# Broad screen used to decide whether a bill is worth fetching full text for.
# Anything touching elections, voting or representation passes.
ELECTION_SCREEN = re.compile(
    r"\b(elect|vot(e|er|ing)|ballot|primar(y|ies)|candidate|redistrict|apportion|"
    r"political subdivision|precinct|polling|canvass|runoff|run-off|nominat|"
    r"secretary of state|representation|ranked|plurality|at-large|proportional)",
    re.IGNORECASE,
)


def election_related(text: str) -> bool:
    return bool(ELECTION_SCREEN.search(text or ""))
