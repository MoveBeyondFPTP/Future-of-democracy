"""Colorado: leg.colorado.gov bill search. Each results page lists 25 bills with
short and long title, last action, subjects and sponsors. Election-related
bills then get their detail page (official summary and full history).
The site rate-limits, so requests are spaced about two seconds apart.
"""

from __future__ import annotations

import re
import time

import lxml.html

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable

BASE = "https://leg.colorado.gov"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
DETAIL_TTL = 7 * 86400


def _clean(el) -> str:
    return re.sub(r"\s+", " ", el.text_content()).strip() if el is not None else ""


def _page(ctx: Context, site_name: str, page: int):
    data = {"q": "", "sessions[]": site_name, "show_filters": "", "sort": "Last Action Descending", "page": page}
    ctx.client._wait()
    ctx.client.count += 1
    r = ctx.client.s.post(f"{BASE}/bills/bill-search", data=data, headers=HEADERS, timeout=90)
    r.raise_for_status()
    return lxml.html.fromstring(r.content)


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]                 # "2026A"
    site_name = session.get("site_name") or session["name"]
    ctx.client.delay = max(ctx.client.delay, 2.1)
    results, page, last_page = [], 1, 1
    while page <= last_page and page <= 200:
        doc = _page(ctx, site_name, page)
        if page == 1:
            nums = [int(b.text_content().strip()) for b in doc.xpath("//button[@data-page]") if b.text_content().strip().isdigit()]
            last_page = max(nums) if nums else 1
        blocks = doc.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " bill-result ")]')
        if not blocks:
            break
        for blk in blocks:
            h2 = blk.xpath(".//h2")
            num = _clean(h2[0]) if h2 else ""
            # keep only this session's bills (search can include others)
            meta = _clean(blk.xpath('.//div[contains(@class,"bill-type")]')[0]) if blk.xpath('.//div[contains(@class,"bill-type")]') else ""
            if site_name.lower() not in meta.lower():
                continue
            a = blk.xpath('.//a[contains(@class,"all-bills-data-heading")]')
            row = {"num": num, "kind": meta.split("|")[0].strip().lower(), "short": _clean(a[0]) if a else "",
                   "href": a[0].get("href") if a else ""}
            for p in blk.xpath(".//p"):
                t = _clean(p)
                if t.upper().startswith("LONG TITLE:"):
                    row["long"] = t.split(":", 1)[1].strip()
            txt = _clean(blk)
            m = re.search(r"LAST ACTION:\s*(\d{2}/\d{2}/\d{4})\s*\|\s*(.*?)\s*(SUBJECTS:|SPONSORS:|$)", txt)
            if m:
                row["last_date"], row["last"] = iso_date(m.group(1)), m.group(2).strip()
            row["subjects"] = [_clean(li) for li in blk.xpath('.//span[contains(text(),"SUBJECTS")]/following::ul[1]/li')]
            row["sponsors"] = [_clean(li) for li in blk.xpath('.//div[contains(@class,"sponsors")]//li')]
            results.append(row)
        page += 1
        if ctx.out_of_time():
            ctx.warn("ran out of time while listing")
            break
    if not results:
        raise SessionNotAvailable(code)

    details = ctx.cache.setdefault(f"details_{code}", {})
    now = time.time()
    bills, seen = [], set()
    for row in results:
        num = row["num"]                     # "HB26-1362"
        if not num or num in seen:
            continue
        seen.add(num)
        prefix = re.match(r"[A-Z]+", num).group(0) if re.match(r"[A-Z]+", num) else ""
        url = BASE + row["href"] if row["href"].startswith("/") else (row["href"] or f"{BASE}/bills/{num}")
        bill = {
            "id": f"co-{code}-{num}",
            "state": "CO",
            "session": code,
            "session_name": session["name"],
            "number": num,
            "chamber": "House" if prefix.startswith("H") else "Senate",
            "type": {"bill": "bill", "resolution": "resolution", "memorial": "memorial",
                     "concurrent resolution": "concurrent resolution"}.get(row["kind"], row["kind"] or "bill"),
            "title": row["short"] or row.get("long", ""),
            "summary": row.get("long", ""),
            "subjects": row.get("subjects", []),
            "sponsors": [{"name": s, "role": "primary"} for s in row.get("sponsors", []) if s],
            "url": url,
        }
        if row.get("last"):
            bill["actions"] = [{"date": row.get("last_date", ""), "chamber": "", "text": row["last"]}]
        screen_text = f"{row['short']} {row.get('long', '')} {' '.join(row.get('subjects', []))}"
        if ctx.screen(screen_text) and not ctx.out_of_time():
            d = details.get(num)
            stale = not d or d.get("last") != row.get("last") or now - d.get("fetched", 0) > DETAIL_TTL
            if stale:
                d = _detail(ctx, url) or d
                if d:
                    d["last"] = row.get("last")
                    details[num] = d
            if d:
                if d["actions"]:
                    bill["actions"] = d["actions"]
                if d["summary"]:
                    bill["summary"] = d["summary"] + (f"\n\nLong title: {row['long']}" if row.get("long") else "")
                if d["text_url"]:
                    bill["text_url"] = d["text_url"]
        bills.append(finalize(bill))
    ctx.log.info("[CO %s] %d bills", code, len(bills))
    return bills


def _detail(ctx: Context, url: str) -> dict | None:
    try:
        r = ctx.client.get(url, headers=HEADERS, timeout=60)
        if r.status_code != 200:
            ctx.warn(f"detail {url}: HTTP {r.status_code}")
            return None
        doc = lxml.html.fromstring(r.content)
        doc.make_links_absolute(url)
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"detail {url}: {e}")
        return None
    actions = []
    for tr in doc.xpath("//table//tr[td]"):
        cells = [_clean(c) for c in tr.xpath("./td")]
        if len(cells) >= 3 and re.match(r"\d{2}/\d{2}/\d{4}$", cells[0]) and cells[1] in ("House", "Senate", "Governor", "Joint", "Legislature"):
            actions.append({"date": iso_date(cells[0]), "chamber": cells[1], "text": cells[2]})
    actions.sort(key=lambda a: a["date"])
    text = _clean(doc)
    summary = ""
    m = re.search(r"Bill Summary:\s*(.*?)(?:\(Note: This summary applies.*?\))?\s*(?:bill-detail#toggle|Read more|Prime Sponsors)", text)
    if m:
        summary = m.group(1).strip()
    pdf = doc.xpath('//button[contains(normalize-space(.), "Recent Bill")]/@data-url')
    text_url = (BASE + pdf[0] if pdf[0].startswith("/") else pdf[0]) if pdf else ""
    return {"fetched": time.time(), "actions": actions, "summary": summary, "text_url": text_url}
