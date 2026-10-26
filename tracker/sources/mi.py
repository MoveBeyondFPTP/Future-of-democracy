"""Michigan: legislature.mi.gov. One search request lists every bill and joint
resolution of a session with its description and last action. The site's own
full-text search is also asked for each topic's key phrases, so bills that
only mention them deep in the text are caught. Election-related bills get
their detail page (history, sponsors) and current text.
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

import lxml.html

from ..model import derive_status, finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

BASE = "https://legislature.mi.gov"
SEARCH = (BASE + "/Search/ExecuteSearch?chamber=&docTypesList=HB%2CSB&docTypesList=HR%2CSR"
          "&docTypesList=HCR%2CSCR&docTypesList=HJR%2CSJR&sessions={s}&sponsor=&number=&dateFrom=&dateTo="
          "&contentFullText={q}")
# Plain phrases sent to Michigan's full-text search (the regex categories
# still decide what is tracked; these only pick which bills get read closely).
FULLTEXT_PHRASES = [
    "ranked choice", "ranked-choice", "instant runoff", "voting rights act", "vote dilution",
    "racially polarized", "proportional representation", "multimember district",
    "multi-member district", "cumulative voting", "approval voting", "single transferable vote",
]
TYPES = {"B": "bill", "R": "resolution", "CR": "concurrent resolution", "JR": "joint resolution"}
DETAIL_TTL = 7 * 86400


def _rows(ctx: Context, session: str, q: str = "") -> list[dict]:
    r = ctx.client.get(SEARCH.format(s=session, q=quote_plus(q)), timeout=180)
    r.raise_for_status()
    doc = lxml.html.fromstring(r.content)
    out = []
    for tr in doc.xpath("//table//tr[td]"):
        a = tr.xpath("./td[1]//a")
        if not a:
            continue
        m = re.search(r"objectName=([^&\"]+)", a[0].get("href", ""), re.I)
        if not m:
            continue
        desc_cell = tr.xpath("./td[3]")
        desc_html = lxml.html.tostring(desc_cell[0], encoding="unicode") if desc_cell else ""
        parts = re.split(r"<br\s*/?>", desc_html, maxsplit=1, flags=re.I)
        desc = strip_html(parts[0])
        last = strip_html(parts[1]) if len(parts) > 1 else ""
        last = re.sub(r"^Last Action:\s*", "", last)
        out.append({"obj": m.group(1), "label": a[0].text_content().strip(), "desc": desc, "last": last})
    return out


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]        # "2025-2026"
    rows = _rows(ctx, code)
    if not rows:
        raise SessionNotAvailable(code)

    flagged = set()
    for phrase in FULLTEXT_PHRASES:
        try:
            flagged |= {r["obj"] for r in _rows(ctx, code, f'"{phrase}"')}
        except Exception as e:  # noqa: BLE001
            ctx.warn(f"full-text search '{phrase}': {e}")

    details = ctx.cache.setdefault(f"details_{code}", {})
    texts = ctx.cache.setdefault("text_cats", {})
    now = time.time()
    bills, seen = [], set()
    for r in rows:
        obj = r["obj"]                         # "2025-HB-4707"
        if obj in seen:
            continue
        seen.add(obj)
        parts = obj.split("-")
        if len(parts) < 3:
            continue
        prefix, num = parts[1], parts[2].lstrip("0") or parts[2]
        kind = TYPES.get(prefix[1:], "bill")
        bill = {
            "id": f"mi-{code}-{prefix}{num}",
            "state": "MI",
            "session": code,
            "session_name": session["name"],
            "number": f"{prefix} {num}",
            "chamber": "House" if prefix.startswith("H") else "Senate",
            "type": kind,
            "title": r["desc"],
            "url": f"{BASE}/Bills/Bill?ObjectName={obj}",
            "last_action": r["last"],
            "status": derive_status([{"text": r["last"]}]) if r["last"] else "introduced",
        }
        if "PA " in r["label"]:
            bill["status"] = "enacted"
        if (obj in flagged or ctx.screen(r["desc"])) and not ctx.out_of_time():
            d = details.get(obj)
            if not d or now - d.get("fetched", 0) > (0 if d.get("relevant") else DETAIL_TTL):
                d = _detail(ctx, bill["url"]) or d
                if d:
                    details[obj] = d
            if d:
                bill["actions"] = d["actions"]
                bill["sponsors"] = d["sponsors"]
                bill["text_url"] = d["text_url"]
                bill.pop("last_action", None)
                if bill["status"] != "enacted":
                    bill["status"] = derive_status(d["actions"]) if d["actions"] else bill["status"]
                t = d["text_url"]
                if t and t not in texts:
                    try:
                        texts[t] = ctx.classify(strip_html(ctx.client.get_text(t)))
                    except Exception as e:  # noqa: BLE001
                        ctx.warn(f"text {obj}: {e}")
                        texts[t] = {}
                if texts.get(t):
                    bill["text_categories"] = texts[t]
                d["relevant"] = bool(ctx.classify(r["desc"]) or texts.get(t))
        bills.append(finalize(bill))
    ctx.log.info("[MI %s] %d bills, %d flagged by full-text search", code, len(bills), len(flagged))
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
    for tr in doc.xpath("//table//tr[td]"):
        cells = [re.sub(r"\s+", " ", c.text_content()).strip() for c in tr.xpath("./td")]
        if len(cells) >= 3 and re.match(r"\d{1,2}/\d{1,2}/\d{4}", cells[0]):
            j = cells[1]
            chamber = "House" if j.startswith("HJ") else "Senate" if j.startswith("SJ") else ""
            actions.append({"date": iso_date(cells[0]), "chamber": chamber, "text": cells[2]})
    sponsors = []
    h2 = doc.xpath('//h2[normalize-space()="Sponsors"]')
    if h2:
        node = h2[0].getnext()
        hops = 0
        while node is not None and node.tag != "h2" and hops < 6:
            for i, a in enumerate(node.xpath(".//a")):
                nm = re.sub(r"\s*\(District \d+\)\s*", "", a.text_content()).strip()
                if nm:
                    sponsors.append({"name": nm, "role": "primary" if not sponsors else "cosponsor"})
            node = node.getnext()
            hops += 1
    htm = [h for h in doc.xpath('//a[contains(@href, "/htm/")]/@href') if "billanalysis" not in h]
    return {"fetched": time.time(), "actions": actions, "sponsors": sponsors[:60],
            "text_url": htm[-1] if htm else ""}
