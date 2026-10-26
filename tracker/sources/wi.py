"""Wisconsin: docs.legis.wisconsin.gov. Each list page shows every proposal of
one type with its status and relating clause; election-related proposals then
get their history page and introduced text.
"""

from __future__ import annotations

import re
import time

import lxml.html

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

BASE = "https://docs.legis.wisconsin.gov"
LISTS = [("asm", "bill", "AB", "bill"), ("sen", "bill", "SB", "bill"),
         ("asm", "joint_resolution", "AJR", "joint resolution"), ("sen", "joint_resolution", "SJR", "joint resolution"),
         ("asm", "resolution", "AR", "resolution"), ("sen", "resolution", "SR", "resolution")]
DETAIL_TTL = 7 * 86400


def _status(s: str) -> str | None:
    t = s.lower()
    if "enacted" in t or re.search(r"\bact \d+", t) or "published" in t:
        return "enacted"
    if "veto" in t:
        return "vetoed"
    if any(w in t for w in ("failed", "withdrawn", "rejected", "indefinitely postponed", "tabled", "nonconcurred")):
        return "failed"
    if "adopted" in t or "concurred" in t:
        return "passed_both" if "concurred" in t else "passed_one"
    if "passed" in t or "available for scheduling" in t:
        return "passed_one" if "passed" in t else "committee"
    if t.strip():
        return "committee"
    return None


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]     # biennium start year, e.g. "2025"
    details = ctx.cache.setdefault(f"details_{code}", {})
    texts = ctx.cache.setdefault("text_cats", {})
    now = time.time()
    bills, any_list = [], False
    for house, kind_path, prefix, kind in LISTS:
        url = f"{BASE}/{code}/proposals/reg/{house}/{kind_path}"
        r = ctx.client.get(url, timeout=120)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        doc = lxml.html.fromstring(r.content)
        items = doc.xpath('//ul[contains(@class,"infoLinks")]/li')
        if items:
            any_list = True
        for li in items:
            cols = li.xpath('.//div[contains(@class,"row-fluid")]/div')
            if len(cols) < 3:
                continue
            href = cols[0].xpath(".//a/@href")
            if not href:
                continue
            slug = href[0].rstrip("/").rsplit("/", 1)[-1]          # "ab89"
            m = re.match(r"[a-z]+(\d+)", slug)
            if not m:
                continue
            n = m.group(1)
            status_txt = cols[1].text_content().strip()
            title = re.sub(r"\s+", " ", cols[2].text_content()).strip()
            title = re.sub(r"^Relating to:\s*", "", title)
            title = title[:1].upper() + title[1:]
            bill = {
                "id": f"wi-{code}-{prefix}{n}",
                "state": "WI",
                "session": code,
                "session_name": session["name"],
                "number": f"{prefix} {n}",
                "chamber": "Assembly" if house == "asm" else "Senate",
                "type": kind,
                "title": title,
                "url": BASE + href[0] if href[0].startswith("/") else href[0],
                "text_url": f"{BASE}/{code}/related/proposals/{slug}",
                "status": _status(status_txt.split(" - ", 1)[-1]) or "introduced",
                "last_action": status_txt.split(" - ", 1)[-1],
            }
            if ctx.screen(title) and not ctx.out_of_time():
                d = details.get(slug)
                if not d or now - d.get("fetched", 0) > (0 if d.get("relevant") else DETAIL_TTL):
                    d = _detail(ctx, bill["url"]) or d
                    if d:
                        details[slug] = d
                if d:
                    bill["actions"] = d["actions"]
                    bill["sponsors"] = d["sponsors"]
                    bill.pop("last_action", None)
                t = bill["text_url"]
                if t not in texts:
                    try:
                        texts[t] = ctx.classify_body(strip_html(ctx.client.get_text(t)))
                    except Exception as e:  # noqa: BLE001
                        ctx.warn(f"text {slug}: {e}")
                        texts[t] = {}
                if texts.get(t):
                    bill["text_categories"] = texts[t]
                if d is not None:
                    d["relevant"] = bool(ctx.classify(title) or texts.get(t))
            bills.append(finalize(bill))
    if not any_list:
        raise SessionNotAvailable(code)
    ctx.log.info("[WI %s] %d proposals", code, len(bills))
    return bills


def _detail(ctx: Context, url: str) -> dict | None:
    try:
        r = ctx.client.get(url, timeout=60)
        if r.status_code != 200:
            return None
        doc = lxml.html.fromstring(r.content)
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"detail {url}: {e}")
        return None
    actions, sponsors = [], []
    seen = set()
    for tr in doc.xpath("//table//tr"):
        cells = [re.sub(r"\s+", " ", c.text_content()).strip() for c in tr.xpath("./td")]
        if len(cells) < 2:
            continue
        m = re.match(r"(\d{1,2}/\d{1,2}/\d{4})\s*(Asm\.|Sen\.)?", cells[0])
        if not m:
            continue
        key = (cells[0], cells[1])
        if key in seen:
            continue
        seen.add(key)
        chamber = {"Asm.": "Assembly", "Sen.": "Senate"}.get(m.group(2) or "", "")
        actions.append({"date": iso_date(m.group(1)), "chamber": chamber, "text": cells[1]})
        if not sponsors:
            mm = re.match(r"Introduced by (?:Representatives?|Senators?|Joint Legislative Council|Committee on [^;]+)\s*(.*)", cells[1])
            if mm:
                names = re.split(r",\s*|;\s*| and ", mm.group(1))
                for i, nm in enumerate(n.strip(" .") for n in names):
                    if nm and not nm.lower().startswith(("cosponsored", "by ")):
                        sponsors.append({"name": nm, "role": "primary" if i == 0 else "cosponsor"})
    actions.sort(key=lambda a: a["date"])
    return {"fetched": time.time(), "actions": actions, "sponsors": sponsors[:40]}
