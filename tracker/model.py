"""The normalized bill record every state source produces, plus status logic.

A bill record is a plain dict (so it serializes straight to JSON):

  id            "tx-89R-HB1"   unique across states and sessions
  state         "TX"
  session       "89R"          the legislature's own session code
  session_name  "89th Legislature (2025)"
  number        "HB 1"
  chamber       "House" | "Senate" | "Joint" | ""
  type          "bill" | "resolution" | "joint resolution" | ...
  title         official title / caption
  summary       official summary, synopsis or digest ("" if none)
  subjects      list of official subject terms
  sponsors      [{"name": str, "role": "primary"|"cosponsor"}]
  actions       [{"date": "YYYY-MM-DD", "chamber": str, "text": str}]  oldest first
  hearings      [{"date": "YYYY-MM-DDTHH:MM", "chamber": str, "committee": str}]
  status        one of STATUSES (derived)
  introduced    "YYYY-MM-DD" | ""
  last_action   text of most recent action
  last_action_date
  url           official bill page
  text_url      link to current bill text ("" if unknown)
  categories    classification result (see classify.py)
"""

from __future__ import annotations

import re
from datetime import datetime

STATUSES = [
    "introduced",     # filed / prefiled / first reading
    "committee",      # referred to or heard in committee
    "passed_one",     # passed one chamber
    "passed_both",    # passed both chambers / sent to governor
    "enacted",        # signed or otherwise became law
    "vetoed",
    "failed",         # killed, withdrawn, carried over or died
]

STATUS_LABELS = {
    "introduced": "Introduced",
    "committee": "In committee",
    "passed_one": "Passed one chamber",
    "passed_both": "Passed legislature",
    "enacted": "Enacted",
    "vetoed": "Vetoed",
    "failed": "Failed / dead",
}

_ENACTED = re.compile(
    r"(signed by (the )?governor|approved by (the )?governor|governor('s)? (signed|approved|action: approved)|"
    r"became law|becomes law|effective without (the )?governor|without (the )?governor'?s? signature|"
    r"enacted|chaptered|acts of \d{4},? chapter|\bchapter \d+ of the acts|signed by governor|"
    r"approved by governor|governor approved|veto overridden|overrid(den|e) .*veto)",
    re.I,
)
_VETOED = re.compile(r"\bveto(ed)?\b", re.I)
_TO_GOV = re.compile(
    r"(sent to (the )?governor|presented to (the )?governor|delivered to (the )?governor|"
    r"enrolled|to governor|passed both|laid before (the )?governor|communicated to governor)",
    re.I,
)
_PASSED = re.compile(
    r"(\bpassed(?! by)(?! over)\b|engrossed|third reading.{0,20}(passed|adopted)|"
    r"read (a )?third time and passed|adopted by (the )?(house|senate)|record vote|"
    r"\bagreed to\b)",
    re.I,
)
_FAILED = re.compile(
    r"(passed by indefinitely|continued to \d{4}|left in (committee|appropriations|finance)|"
    r"failed|\bdied\b|indefinitely postponed|tabled|reported unfavorabl|unfavorable report|"
    r"withdrawn|leave to withdraw|stricken|study order|accompanied a study|"
    r"incorporated into|killed|no further action|laid on the table)",
    re.I,
)
_COMMITTEE = re.compile(r"(referred|committee|hearing|reported|re-referred)", re.I)


def derive_status(actions: list[dict]) -> str:
    """Best-effort status from action history. States with explicit status
    fields (VA, MD) override this in their source module."""
    if not actions:
        return "introduced"
    progress = 0
    chambers_passed = set()
    vetoed = False
    for a in actions:
        text = a.get("text", "")
        if _ENACTED.search(text) and not re.search(r"veto", text, re.I) or re.search(r"veto overridden|override.*(passed|succeeded)", text, re.I):
            progress = max(progress, 5)
            continue
        if _VETOED.search(text) and not re.search(r"override", text, re.I):
            vetoed = True
            continue
        if _TO_GOV.search(text):
            progress = max(progress, 3)
            continue
        if _FAILED.search(text):
            continue
        if _PASSED.search(text):
            progress = max(progress, 2)
            if a.get("chamber"):
                chambers_passed.add(a["chamber"].lower())
            continue
        if _COMMITTEE.search(text):
            progress = max(progress, 1)
    if progress >= 5:
        return "enacted"
    if vetoed:
        return "vetoed"
    last = actions[-1].get("text", "")
    if _FAILED.search(last):
        return "failed"
    if progress >= 3 or len({c for c in chambers_passed if c in ("house", "senate", "lower", "upper")}) >= 2:
        return "passed_both"
    return ["introduced", "committee", "passed_one"][min(progress, 2)]


def iso_date(value: str) -> str:
    """Convert the many date formats legislatures use to YYYY-MM-DD."""
    if not value:
        return ""
    value = value.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", value)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return f"{y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    for f in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def finalize(bill: dict) -> dict:
    """Fill derived fields and defaults."""
    for k, default in (
        ("summary", ""), ("subjects", []), ("sponsors", []), ("actions", []),
        ("hearings", []), ("text_url", ""), ("chamber", ""), ("type", "bill"),
    ):
        bill.setdefault(k, default)
    acts = [a for a in bill["actions"] if a.get("date")]
    acts.sort(key=lambda a: a["date"])
    bill["actions"] = acts
    if acts:
        bill["last_action"] = acts[-1]["text"]
        bill["last_action_date"] = acts[-1]["date"]
        bill.setdefault("introduced", acts[0]["date"])
    else:
        bill.setdefault("last_action", "")
        bill.setdefault("last_action_date", bill.get("introduced", ""))
        bill.setdefault("introduced", "")
    if not bill.get("status"):
        bill["status"] = derive_status(acts)
    return bill


def classification_text(bill: dict) -> str:
    return " \n ".join(
        [bill.get("title", ""), bill.get("summary", ""), " ; ".join(bill.get("subjects", []))]
    )
