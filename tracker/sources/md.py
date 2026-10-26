"""Maryland: the General Assembly's master list file
(mgaleg.maryland.gov/<session>/misc/billsmasterlist/legislation.json).
One request returns every bill with synopsis, subjects, status, and the
dates of each reading and committee hearing.
"""

from __future__ import annotations

import re

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable

URL = "https://mgaleg.maryland.gov/{s}/misc/billsmasterlist/legislation.json"
TYPES = {"HB": "bill", "SB": "bill", "HJ": "joint resolution", "SJ": "joint resolution"}


def _status(b: dict) -> str | None:
    st = (b.get("Status") or "").lower()
    if (b.get("ChapterNumber") or "").strip() or "approved by the governor" in st or "enacted" in st:
        return "enacted"
    if "veto" in st and "overrid" not in st:
        return "vetoed"
    if b.get("PassedByMGA"):
        return "passed_both"
    if any(w in st for w in ("unfavorable", "withdrawn", "failed", "died")):
        return "failed"
    if (b.get("ThirdReadingActionHouseOfOrigin") or "").lower().startswith("passed"):
        return "passed_one"
    if b.get("FirstReadingDateHouseOfOrigin") or b.get("CommitteePrimaryOrigin"):
        return "committee"
    return "introduced"


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]
    r = ctx.client.get(URL.format(s=code), headers={"Accept": "application/json"}, timeout=180)
    if r.status_code == 404 or "json" not in (r.headers.get("content-type") or ""):
        raise SessionNotAvailable(code)
    r.raise_for_status()
    rows = r.json()
    bills = []
    for b in rows:
        raw = (b.get("BillNumber") or "").strip()
        m = re.match(r"([A-Z]+)0*(\d+)", raw)
        if not m:
            continue
        prefix, n = m.group(1), m.group(2)
        num = f"{prefix} {n}"
        origin = "House" if prefix.startswith("H") else "Senate"
        other = "Senate" if origin == "House" else "House"

        acts, hearings = [], []

        def add(date, chamber, text):
            d = iso_date(date or "")
            if d:
                acts.append({"date": d, "chamber": chamber, "text": text})

        for side, chamber, cmte_key in (("HouseOfOrigin", origin, "CommitteePrimaryOrigin"),
                                        ("OppositeHouse", other, "CommitteePrimaryOpposite")):
            cmte = (b.get(cmte_key) or "").strip()
            add(b.get(f"FirstReadingDate{side}"), chamber,
                f"First reading{', referred to ' + cmte if cmte else ''}")
            for which in ("Primary", "Secondary"):
                h = b.get(f"HearingDateTime{which}{side}")
                c2 = (b.get(f"Committee{which}{'Origin' if side == 'HouseOfOrigin' else 'Opposite'}") or "").strip()
                if h:
                    hearings.append({"date": h[:16], "chamber": chamber, "committee": c2})
                    add(h, chamber, f"Hearing{' in ' + c2 if c2 else ''}")
            if b.get(f"ReportAction{side}"):
                add(b.get(f"ReportDate{side}"), chamber, f"Committee report: {b[f'ReportAction{side}']}")
            if b.get(f"SecondReadingAction{side}"):
                add(b.get(f"SecondReadingDate{side}"), chamber, f"Second reading: {b[f'SecondReadingAction{side}']}")
            if b.get(f"ThirdReadingAction{side}"):
                add(b.get(f"ThirdReadingDate{side}"), chamber, f"Third reading: {b[f'ThirdReadingAction{side}']}")

        status_text = (b.get("Status") or "").strip()
        if status_text and acts:
            last = max(a["date"] for a in acts)
            if not any(a["text"] == status_text for a in acts):
                acts.append({"date": last, "chamber": "", "text": status_text})

        sponsors = []
        primary = (b.get("SponsorPrimary") or "").strip()
        if primary:
            sponsors.append({"name": primary, "role": "primary"})
        for s in b.get("Sponsors") or []:
            nm = (s.get("Name") or "").strip()
            if nm and nm != primary:
                sponsors.append({"name": nm, "role": "cosponsor"})

        subjects = [x.get("Name", "") for x in (b.get("BroadSubjects") or []) + (b.get("NarrowSubjects") or [])]
        version = (b.get("BillVersion") or "F").strip() or "F"
        bill = {
            "id": f"md-{code}-{prefix}{n}",
            "state": "MD",
            "session": code,
            "session_name": session["name"],
            "number": num,
            "chamber": origin,
            "type": TYPES.get(prefix, "bill"),
            "title": (b.get("Title") or "").strip(),
            "summary": (b.get("Synopsis") or "").strip(),
            "subjects": [s for s in subjects if s],
            "sponsors": sponsors,
            "actions": acts,
            "hearings": hearings,
            "status": _status(b),
            "url": f"https://mgaleg.maryland.gov/mgawebsite/Legislation/Details/{raw.lower()}?ys={code}",
            "text_url": f"https://mgaleg.maryland.gov/{code}/bills/{prefix[:2].lower()}/{raw.lower()}{version}.pdf",
        }
        if b.get("CrossfileBillNumber"):
            bill["crossfile"] = b["CrossfileBillNumber"]
        if b.get("ChapterNumber"):
            bill["chapter"] = b["ChapterNumber"]
        bills.append(finalize(bill))
    ctx.log.info("[MD %s] %d bills", code, len(bills))
    return bills
