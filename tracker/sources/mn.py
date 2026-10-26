"""Minnesota: the Revisor of Statutes' Bill Status API
(www.revisor.mn.gov/bills/service). A search request returns bill numbers and
descriptions 500 at a time; election-related bills then get their full XML
status record (authors, actions) and latest text.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

SEARCH = ("https://www.revisor.mn.gov/bills/status_result.php?body={body}&search=basic&session={code}"
          "&location={body}&bill={lo}-{hi}&bill_type={btype}&rev_number=&submit_bill=GO&keyword_type=all"
          "&keyword=&keyword_field_text=1&titleword=&format=xml")
CHUNK = 500
DETAIL_TTL = 3 * 86400


def _https(u: str) -> str:
    u = (u or "").strip()
    if u.startswith("//"):
        return "https:" + u
    if u and not u.startswith("http"):
        return "https://" + u
    return u


def _search(ctx: Context, code: str, body: str, btype: str) -> list[dict]:
    out, lo, empty = [], 1, 0
    while empty < 2 and lo < 20000:
        url = SEARCH.format(body=body, code=code, lo=lo, hi=lo + CHUNK - 1, btype=btype)
        r = ctx.client.get(url, timeout=120)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        rows = root.findall("BILL_RESULT")
        if not rows:
            empty += 1
        for b in rows:
            out.append({
                "type": b.findtext("FILE_TYPE") or "",
                "num": b.findtext("FILE_NUMBER") or "",
                "status": _https(b.findtext("STATUS_XML_URI")),
                "text": _https(b.findtext("LATEST_TEXT_HTML_URI")),
                "desc": (b.findtext("DESCRIPTION") or "").strip(),
            })
        lo += CHUNK
    return out


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]            # e.g. "0942025": session type 0, 94th Legislature, 2025
    year = code[-4:]
    rows = []
    for body in ("House", "Senate"):
        for btype in ("bill", "resolution"):
            try:
                rows += _search(ctx, code, body, btype)
            except ET.ParseError:
                continue
    if not rows:
        raise SessionNotAvailable(code)

    details = ctx.cache.setdefault(f"details_{code}", {})
    texts = ctx.cache.setdefault("text_cats", {})
    now = time.time()
    bills, seen = [], set()
    for r in rows:
        num = f"{r['type']} {r['num']}"
        if num in seen or not r["num"]:
            continue
        seen.add(num)
        chamber = "House" if r["type"].startswith("H") else "Senate"
        bill = {
            "id": f"mn-{code}-{r['type']}{r['num']}",
            "state": "MN",
            "session": code,
            "session_name": session["name"],
            "number": num,
            "chamber": chamber,
            "type": "resolution" if "R" in r["type"][1:] else "bill",
            "title": r["desc"],
            "url": f"https://www.revisor.mn.gov/bills/bill.php?b={chamber}&f={r['type']}{r['num']}&ssn=0&y={year}",
            "text_url": r["text"],
        }
        if ctx.screen(r["desc"]) and r["status"] and not ctx.out_of_time():
            d = details.get(num)
            if not d or now - d.get("fetched", 0) > (0 if d.get("relevant") else DETAIL_TTL):
                d = _detail(ctx, r["status"]) or d
                if d:
                    details[num] = d
            if d:
                bill["sponsors"] = d["sponsors"]
                bill["actions"] = d["actions"]
                if d.get("companion"):
                    bill["companion"] = d["companion"]
            if r["text"] and r["text"] not in texts:
                try:
                    texts[r["text"]] = ctx.classify(strip_html(ctx.client.get_text(r["text"])))
                except Exception as e:  # noqa: BLE001
                    ctx.warn(f"text {num}: {e}")
                    texts[r["text"]] = {}
            if texts.get(r["text"]):
                bill["text_categories"] = texts[r["text"]]
            if d is not None:
                d["relevant"] = bool(ctx.classify(r["desc"]) or bill.get("text_categories"))
        bills.append(finalize(bill))
    ctx.log.info("[MN %s] %d bills", code, len(bills))
    return bills


def _detail(ctx: Context, url: str) -> dict | None:
    try:
        r = ctx.client.get(url, timeout=60)
        if r.status_code != 200:
            return None
        root = ET.fromstring(r.content)
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"detail {url}: {e}")
        return None
    sponsors = []
    for i, a in enumerate(root.iterfind("AUTHORS/*/AUTHOR")):
        nm = (a.findtext("MEMBER_NAME") or "").strip()
        if nm:
            sponsors.append({"name": nm, "role": "primary" if i == 0 else "cosponsor"})
    actions = []
    for grp in root.findall("ACTIONS/*"):
        chamber = {"HOUSE": "House", "SENATE": "Senate"}.get(grp.tag, grp.tag.title())
        for a in grp.findall("ACTION"):
            text = (a.findtext("ACTION_TEXT") or "").strip()
            cmte = (a.findtext("COMMITTEE_NAME") or "").strip()
            desc = (a.findtext("ACTION_DESCRIPTION") or "").strip()
            if cmte:
                text = f"{text} {cmte}".strip()
            if desc and len(desc) < 160 and "added" not in text.lower():
                text = f"{text}: {desc}"
            actions.append({"date": iso_date(a.findtext("ACTION_DATE") or ""), "chamber": chamber, "text": text})
    comp = ""
    if root.findtext("COMPANION_TYPE") and root.findtext("COMPANION_NUMBER"):
        comp = f"{root.findtext('COMPANION_TYPE')} {root.findtext('COMPANION_NUMBER')}"
    return {"fetched": time.time(), "sponsors": sponsors, "actions": actions, "companion": comp}
