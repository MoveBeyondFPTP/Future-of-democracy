"""Virginia: the Legislative Information System's public CSV files
(lis.blob.core.windows.net/lisfiles/<session>/...). Four files per session
cover every bill, its official summaries, history and patrons; no API key.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

BASE = "https://lis.blob.core.windows.net/lisfiles/{s}/{f}"
TYPES = {"HB": "bill", "SB": "bill", "HJ": "joint resolution", "SJ": "joint resolution",
         "HR": "resolution", "SR": "resolution"}


def _csv(ctx: Context, session: str, name: str, required: bool = False) -> list[dict]:
    r = ctx.client.get(BASE.format(s=session, f=name), timeout=180)
    if r.status_code == 404:
        if required:
            raise SessionNotAvailable(session)
        return []
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _norm_num(n: str) -> str:
    """'HB0001' -> 'HB1'"""
    m = re.match(r"([A-Z]+)0*(\d+)", (n or "").strip())
    return f"{m.group(1)}{m.group(2)}" if m else (n or "").strip()


def _yes(v: str) -> bool:
    return (v or "").strip().upper() in ("Y", "YES", "TRUE", "1")


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]
    rows = _csv(ctx, code, "BILLS.CSV", required=True)
    if not rows:
        raise SessionNotAvailable(code)

    summaries: dict[str, str] = {}
    all_summaries: dict[str, list] = defaultdict(list)
    for r in _csv(ctx, code, "Summaries.csv"):
        num = _norm_num(r.get("SUM_BILNO", ""))
        txt = strip_html(r.get("SUMMARY_TEXT"))
        # Show the latest version (they're listed oldest first), but classify
        # every version: amendments often drop or add the key language.
        if txt:
            summaries[num] = txt
            all_summaries[num].append(txt)

    history = defaultdict(list)
    for r in _csv(ctx, code, "HISTORY.CSV"):
        desc = (r.get("History_description") or "").strip()
        chamber = {"H": "House", "S": "Senate", "G": "Governor"}.get(desc[:1], "")
        if chamber and desc[1:2] == " ":
            desc = desc[2:]
        history[_norm_num(r.get("Bill_id", ""))].append({
            "date": iso_date(r.get("History_date", "")),
            "chamber": chamber,
            "text": desc,
        })

    sponsors = defaultdict(list)
    for r in _csv(ctx, code, "Sponsors.csv"):
        name = (r.get("MEMBER_NAME") or "").strip()
        if not name:
            continue
        ptype = (r.get("PATRON_TYPE") or "").lower()
        role = "primary" if "chief patron" in ptype and "co" not in ptype else "cosponsor"
        sponsors[_norm_num(r.get("BILL_NUMBER", ""))].append({"name": name, "role": role})

    bills = []
    for r in rows:
        num = _norm_num(r.get("Bill_id", ""))
        if not num:
            continue
        prefix = re.match(r"[A-Z]+", num).group(0)
        status = None
        if _yes(r.get("Approved")) or (r.get("Chapter_id") or "").strip():
            status = "enacted"
        elif _yes(r.get("Vetoed")):
            status = "vetoed"
        elif _yes(r.get("Failed")):
            status = "failed"
        elif _yes(r.get("Carried_over")):
            status = "failed"
        elif _yes(r.get("Passed_house")) and _yes(r.get("Passed_senate")):
            status = "passed_both"
        elif _yes(r.get("Passed_house")) or _yes(r.get("Passed_senate")):
            status = "passed_one"
        acts = history.get(num, [])
        bill = {
            "id": f"va-{code}-{num}",
            "state": "VA",
            "session": code,
            "session_name": session["name"],
            "number": num,
            "chamber": {"H": "House", "S": "Senate"}.get(num[:1], ""),
            "type": TYPES.get(prefix, "bill"),
            "title": (r.get("Bill_description") or "").strip(),
            "summary": summaries.get(num, ""),
            "sponsors": sponsors.get(num) or ([{"name": r["Patron_name"].strip(), "role": "primary"}] if r.get("Patron_name") else []),
            "actions": acts,
            "introduced": iso_date(r.get("Introduction_date", "")),
            "url": f"https://lis.virginia.gov/bill-details/{code}/{num}",
            "text_url": f"https://lis.virginia.gov/bill-details/{code}/{num}/text/{r['Full_text_doc1'].strip()}" if (r.get("Full_text_doc1") or "").strip() else "",
        }
        if len(all_summaries.get(num, [])) > 1:
            bill["text_categories"] = ctx.classify(" ".join(all_summaries[num][:-1]))
        if _yes(r.get("Carried_over")):
            bill["note"] = "Continued to next session"
        if status:
            bill["status"] = status
        finalize(bill)
        if not status and bill["status"] in ("enacted", "passed_both", "vetoed"):
            # Without an explicit flag, don't trust a regex guess this strong.
            bill["status"] = "passed_one"
        bills.append(bill)
    ctx.log.info("[VA %s] %d bills", code, len(bills))
    return bills
