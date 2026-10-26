"""Georgia: the JSON API behind www.legis.ga.gov. The site's pages request a
short-lived token from /api/authentication/token using a key derived from a
value in the site's public JavaScript; this does the same. The search
endpoint lists every bill in a session (caption, sponsors, current status);
election-related bills then get their detail record when available.
"""

from __future__ import annotations

import hashlib
import time

from ..model import derive_status, finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

API = "https://www.legis.ga.gov/api"
DETAIL_CANDIDATES = ["/legislation/detail/{id}", "/Legislation/detail/{id}", "/legislation/{id}"]
DETAIL_TTL = 7 * 86400


def _token(ctx: Context) -> str:
    ts = str(int(time.time() * 1000))
    key = hashlib.sha512(("QFpCwKfd7" + "fjVEXFFwSu36BwwcP83xYgxLAhLYmKk" + "letvarconst" + ts).encode()).hexdigest()
    r = ctx.client.get(f"{API}/authentication/token?key={key}&ms={ts}", timeout=60)
    r.raise_for_status()
    return "Bearer " + r.json()


def scrape(session: dict, ctx: Context) -> list[dict]:
    lib = session["code"]                 # "20252026", "2026EX", "20272028"
    headers = {"Authorization": _token(ctx), "Content-Type": "application/json", "Accept": "application/json"}
    sessions = ctx.client.get(f"{API}/sessions", headers=headers, timeout=60).json()
    sid = next((s["id"] for s in sessions if s.get("library") == lib), None)
    if not sid:
        raise SessionNotAvailable(lib)

    rows, page = [], 0
    while page < 100:
        ctx.client._wait()
        ctx.client.count += 1
        r = ctx.client.s.post(f"{API}/Legislation/Search/250/{page}", json={"sessionId": sid}, headers=headers, timeout=90)
        if r.status_code == 401:
            headers["Authorization"] = _token(ctx)
            continue
        r.raise_for_status()
        res = r.json().get("results", [])
        rows += res
        if len(res) < 250:
            break
        page += 1
    if not rows:
        raise SessionNotAvailable(lib)

    details = ctx.cache.setdefault(f"details_{lib}", {})
    pattern = ctx.cache.get("ga_detail_pattern")
    now = time.time()
    bills, seen = [], set()
    for row in rows:
        lid = row.get("legislationId")
        if not lid or lid in seen:
            continue
        seen.add(lid)
        chamber = "House" if row.get("chamberType") == 1 else "Senate"
        kind = "bill" if row.get("documentType") == 1 else "resolution"
        prefix = ("H" if chamber == "House" else "S") + ("B" if kind == "bill" else "R")
        number = f"{prefix} {row.get('number')}{row.get('suffix') or ''}"
        status_text = (row.get("status") or "").strip()
        sponsors = [{"name": (s.get("name") or "").strip().rstrip(","), "role": "primary" if s.get("sequence") == 1 else "cosponsor"}
                    for s in sorted(row.get("sponsors") or [], key=lambda s: s.get("sequence") or 99) if s.get("name")]
        bill = {
            "id": f"ga-{lib}-{prefix}{row.get('number')}{row.get('suffix') or ''}",
            "state": "GA",
            "session": lib,
            "session_name": session["name"],
            "number": number,
            "chamber": chamber,
            "type": kind,
            "title": (row.get("caption") or "").strip(),
            "sponsors": sponsors,
            "url": f"https://www.legis.ga.gov/legislation/{lid}",
            "actions": [{"date": iso_date(row.get("statusDate") or ""), "chamber": "", "text": status_text}] if status_text else [],
        }
        committees = [c.get("name") for c in (row.get("houseCommittee"), row.get("senateCommittee")) if c and c.get("name")]
        if committees:
            bill["subjects"] = []
            bill["committees"] = committees
        if ctx.screen(bill["title"]) and not ctx.out_of_time() and pattern != "none":
            d = details.get(str(lid))
            if not d or now - d.get("fetched", 0) > (0 if d.get("relevant") else DETAIL_TTL):
                d, pattern = _detail(ctx, lid, headers, pattern)
                if d:
                    details[str(lid)] = d
                ctx.cache["ga_detail_pattern"] = pattern
            if d:
                if d.get("summary"):
                    bill["summary"] = d["summary"]
                if d.get("actions"):
                    bill["actions"] = d["actions"]
                if d.get("text_url"):
                    bill["text_url"] = d["text_url"]
                d["relevant"] = bool(ctx.classify(f"{bill['title']} {d.get('summary', '')}"))
        if not bill.get("actions") or len(bill["actions"]) == 1:
            bill["status"] = derive_status([{"text": status_text}]) if status_text else "introduced"
        bills.append(finalize(bill))
    ctx.log.info("[GA %s] %d bills (detail endpoint: %s)", lib, len(bills), pattern)
    return bills


def _detail(ctx: Context, lid, headers, pattern):
    tries = [pattern] if pattern else DETAIL_CANDIDATES
    for p in tries:
        try:
            r = ctx.client.get(API + p.format(id=lid), headers=headers, timeout=60)
        except Exception:  # noqa: BLE001
            continue
        if r.status_code != 200 or not r.content.strip().startswith((b"{", b"[")):
            continue
        j = r.json()
        if isinstance(j, list):
            j = j[0] if j else {}
        return _parse_detail(j), p
    if not pattern:
        ctx.warn("no Georgia detail endpoint responded; using list data only")
        return None, "none"
    return None, pattern


def _parse_detail(j: dict) -> dict:
    """Pull summary, history and text link from the detail record, tolerating
    differences in field names."""
    def first(*keys):
        for k in keys:
            if j.get(k):
                return j[k]
        return None
    summary = strip_html(first("firstReader", "summary", "firstReaderSummary", "description") or "")
    actions = []
    for a in first("statusHistory", "history", "actions") or []:
        if not isinstance(a, dict):
            continue
        txt = a.get("name") or a.get("description") or a.get("status") or a.get("action") or ""
        dt = a.get("date") or a.get("statusDate") or a.get("actionDate") or ""
        if txt:
            actions.append({"date": iso_date(str(dt)), "chamber": "", "text": str(txt).strip()})
    text_url = ""
    versions = first("versions", "documents") or []
    if versions and isinstance(versions, list) and isinstance(versions[-1], dict):
        text_url = versions[-1].get("url") or versions[-1].get("documentUrl") or ""
    return {"fetched": time.time(), "summary": summary, "actions": actions, "text_url": text_url}
