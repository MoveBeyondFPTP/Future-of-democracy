"""Massachusetts: the Legislature's public JSON API (malegislature.gov/api).

One request returns every document filed in a General Court (title and
sponsors). Election-related documents then get a detail request (summary
"pinslip" and, when published, bill text) and their history.
"""

from __future__ import annotations

import time

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

API = "https://malegislature.gov/api/GeneralCourts/{gc}/Documents"
PAGE = "https://malegislature.gov/Bills/{gc}/{num}"
DETAIL_TTL = 7 * 86400


def _chamber(num: str) -> str:
    return {"H": "House", "S": "Senate"}.get(num[:1], "")


def scrape(session: dict, ctx: Context) -> list[dict]:
    gc = session["code"]
    r = ctx.client.get(API.format(gc=gc), headers={"Accept": "application/json"}, timeout=180)
    if r.status_code in (400, 404):
        raise SessionNotAvailable(gc)
    r.raise_for_status()
    docs = r.json()
    if not docs:
        raise SessionNotAvailable(gc)

    details = ctx.cache.setdefault(f"details_{gc}", {})
    bills = []
    seen = set()
    now = time.time()

    for d in docs:
        num = d.get("BillNumber") or d.get("DocketNumber")
        if not num or num in seen:
            continue
        seen.add(num)
        title = (d.get("Title") or "").strip()
        primary = (d.get("PrimarySponsor") or {}).get("Name")
        sponsors = []
        if primary:
            sponsors.append({"name": primary, "role": "primary"})
        for c in d.get("Cosponsors") or []:
            if c.get("Name") and c.get("Name") != primary:
                sponsors.append({"name": c["Name"], "role": "cosponsor"})

        bill = {
            "id": f"ma-{gc}-{num}",
            "state": "MA",
            "session": gc,
            "session_name": session["name"],
            "number": num,
            "chamber": _chamber(num),
            "type": "bill",
            "title": title,
            "sponsors": sponsors,
            "url": PAGE.format(gc=gc, num=num),
            "text_url": PAGE.format(gc=gc, num=num) + ".pdf" if d.get("BillNumber") else "",
        }
        if d.get("DocketNumber") and d.get("BillNumber"):
            bill["docket"] = d["DocketNumber"]

        if ctx.screen(title) and not ctx.out_of_time():
            cached = details.get(num)
            fresh = False
            if not cached or now - cached.get("fetched", 0) > DETAIL_TTL:
                new = _fetch_detail(ctx, d, gc, num)
                if new:
                    cached, fresh = new, True
                    details[num] = cached
            if cached:
                bill["summary"] = cached.get("summary", "")
                bill["type"] = cached.get("type") or "bill"
                bill["text_categories"] = cached.get("text_categories", {})
                # History is refreshed every run for bills we're tracking.
                if cached.get("relevant") and not fresh:
                    hist = _fetch_history(ctx, gc, num)
                    if hist is not None:
                        cached["actions"] = hist
                bill["actions"] = cached.get("actions", [])
        bills.append(finalize(bill))
    ctx.log.info("[MA %s] %d documents, %d detail requests so far", gc, len(bills), ctx.client.count)
    return bills


def _fetch_detail(ctx: Context, d: dict, gc: str, num: str) -> dict | None:
    url = d.get("Details") or f"{API.format(gc=gc)}/{num}"
    try:
        r = ctx.client.get(url, headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None
        j = r.json()
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"detail {num}: {e}")
        return None
    summary = strip_html(j.get("Pinslip"))
    text = strip_html(j.get("DocumentText"))
    title = j.get("Title") or d.get("Title") or ""
    cats = ctx.classify(" ".join([title, summary, text]))
    out = {
        "fetched": time.time(),
        "summary": summary,
        "type": (j.get("LegislationTypeName") or "bill").lower(),
        "text_categories": cats,
        "relevant": bool(cats),
        "actions": _fetch_history(ctx, gc, num) or [],
    }
    return out


def _fetch_history(ctx: Context, gc: str, num: str) -> list | None:
    try:
        r = ctx.client.get(f"{API.format(gc=gc)}/{num}/DocumentHistoryActions",
                           headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None
        rows = r.json() or []
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"history {num}: {e}")
        return None
    acts = []
    for row in rows:
        if row.get("IsStricken"):
            continue
        acts.append({
            "date": iso_date(row.get("Date", "")),
            "chamber": row.get("Branch") or "",
            "text": (row.get("Action") or "").strip(),
        })
    return acts
