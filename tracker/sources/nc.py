"""North Carolina: the General Assembly's "Filed Bills" feeds (one per chamber
per session, every bill with short and long title), plus each election-related
bill's lookup page for history, sponsors and the current text.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import lxml.html

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

FEED = "https://www.ncleg.gov/Legislation/Bills/FiledBillsFeed/{s}/{c}"
PAGE = "https://www.ncleg.gov/BillLookUp/{s}/{b}"
TYPES = {"B": ("B", "bill"), "R": ("R", "resolution"), "JR": ("JR", "joint resolution")}
DETAIL_TTL = 7 * 86400


def _sentence(s: str) -> str:
    s = (s or "").strip()
    if s.isupper():
        s = s.capitalize()
    return s


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]   # "2025" = 2025-2026 session
    items = []
    for c in ("H", "S"):
        r = ctx.client.get(FEED.format(s=code, c=c), timeout=120)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        items += root.iterfind(".//item")
    # Asking for a session that doesn't exist yet returns the current one's
    # bills, so require bills filed after that session's prefiling could begin.
    floor = f"{int(code) - 1}-11-01"
    if not items or not any(iso_date(it.findtext("fileddate") or "") >= floor for it in items):
        raise SessionNotAvailable(code)

    details = ctx.cache.setdefault(f"details_{code}", {})
    texts = ctx.cache.setdefault("text_cats", {})
    now = time.time()
    bills, seen = [], set()
    for it in items:
        raw = (it.findtext("bill") or "").strip()          # "H1246"
        if not raw or raw in seen:
            continue
        seen.add(raw)
        btype = (it.findtext("billtype") or "B").strip()
        letter, kind = TYPES.get(btype, ("B", "bill"))
        m = re.match(r"([HS])(\d+)", raw)
        if not m:
            continue
        number = f"{m.group(1)}{letter} {m.group(2)}"
        short = (it.findtext("shorttitle") or "").strip()
        long_ = _sentence(it.findtext("longtitle"))
        bill = {
            "id": f"nc-{code}-{raw}",
            "state": "NC",
            "session": code,
            "session_name": session["name"],
            "number": number,
            "chamber": "House" if raw.startswith("H") else "Senate",
            "type": kind,
            "title": short or long_,
            "summary": long_ if short else "",
            "sponsors": [{"name": n.strip(), "role": "primary"} for n in (it.findtext("primarysponsors") or "").split(",") if n.strip()],
            "introduced": iso_date(it.findtext("fileddate") or ""),
            "url": PAGE.format(s=code, b=raw),
        }
        if ctx.screen(f"{short} {long_}") and not ctx.out_of_time():
            d = details.get(raw)
            if not d or now - d.get("fetched", 0) > (0 if d.get("relevant") else DETAIL_TTL):
                d = _detail(ctx, bill["url"]) or d
                if d:
                    details[raw] = d
            if d:
                bill["actions"] = d["actions"]
                bill["sponsors"] = d["sponsors"] or bill["sponsors"]
                bill["subjects"] = d["keywords"]
                bill["text_url"] = d["text_url"]
                t = d["text_url"]
                if t and t not in texts:
                    try:
                        texts[t] = ctx.classify(strip_html(ctx.client.get_text(t)))
                    except Exception as e:  # noqa: BLE001
                        ctx.warn(f"text {raw}: {e}")
                        texts[t] = {}
                if texts.get(t):
                    bill["text_categories"] = texts[t]
                d["relevant"] = bool(ctx.classify(f"{short} {long_}") or texts.get(t))
        bills.append(finalize(bill))
    ctx.log.info("[NC %s] %d bills", code, len(bills))
    return bills


def _detail(ctx: Context, url: str) -> dict | None:
    try:
        r = ctx.client.get(url, timeout=60)
        if r.status_code != 200:
            return None
        doc = lxml.html.fromstring(r.content)
        doc.make_links_absolute(url)
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"detail {url}: {e}")
        return None
    actions = []
    for row in doc.xpath('//h6[contains(text(), "History")]/ancestor::div[contains(@class, "gray-card")]'
                         '//div[@class="card-body"]/div[contains(@class, "row")]'):
        cols = [c.text_content().strip() for c in row.xpath("div")]
        if len(cols) >= 6:
            actions.append({"date": iso_date(cols[1]), "chamber": cols[3] if cols[3] in ("House", "Senate") else "Governor" if cols[3] else "",
                            "text": re.sub(r"\s+", " ", cols[5])})
    text = re.sub(r"\s+", " ", doc.text_content())
    sponsors = []
    m = re.search(r"Sponsors:\s*(.*?)\s*Attributes:", text)
    if m:
        role = "primary"
        for part in m.group(1).split(";"):
            if "(Primary)" in part:
                before, after = part.split("(Primary)", 1)
                if before.strip():
                    sponsors.append({"name": before.strip(), "role": "primary"})
                role = "cosponsor"
                part = after
            nm = part.strip()
            if nm:
                sponsors.append({"name": nm, "role": role})
    keywords = []
    m = re.search(r"Keywords:\s*(.*?)\s*(\$\(function|History)", text)
    if m:
        keywords = [k.strip().title() for k in m.group(1).split(";") if k.strip()][:40]
    text_url = ""
    pdfs = doc.xpath('//a[contains(@href, "/Bills/House/PDF/") or contains(@href, "/Bills/Senate/PDF/")]/@href')
    if pdfs:
        text_url = pdfs[0].replace("/PDF/", "/HTML/").replace(".pdf", ".html")
    return {"fetched": time.time(), "actions": actions, "sponsors": sponsors, "keywords": keywords, "text_url": text_url}
