"""Texas: the Texas Legislative Council's public FTP site
(ftp.legis.state.tx.us), which publishes one XML history file per bill.

Each run lists the history folders and downloads only files whose timestamp
changed since the last run. Election-related bills also get their latest
bill text read (from capitol.texas.gov) so omnibus election bills that bury
an RCV ban in section 40 are still caught.
"""

from __future__ import annotations

import ftplib
import io
import re
import time
import xml.etree.ElementTree as ET

from ..model import finalize, iso_date
from .base import Context, SessionNotAvailable, strip_html

HOST = "ftp.legis.state.tx.us"
TYPE_DIRS = [
    "house_bills", "senate_bills",
    "house_joint_resolutions", "senate_joint_resolutions",
    "house_concurrent_resolutions", "senate_concurrent_resolutions",
    "house_resolutions", "senate_resolutions",
]
TYPE_NAMES = {"B": "bill", "JR": "joint resolution", "CR": "concurrent resolution", "R": "resolution"}
LIST_RE = re.compile(r"^(\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}[AP]M)\s+(<DIR>|\d+)\s+(.+?)\s*$")
OLD_SESSION_REFRESH = 7 * 86400


class FTP:
    """Small reconnecting wrapper around ftplib."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.conn = None

    def _connect(self):
        for attempt in range(5):
            try:
                c = ftplib.FTP(HOST, timeout=90)
                c.login()
                self.conn = c
                return
            except Exception as e:  # noqa: BLE001
                self.ctx.log.warning("TX FTP connect failed (%s), retrying", e)
                time.sleep(2 ** attempt)
        raise RuntimeError("could not connect to Texas FTP")

    def _do(self, fn):
        for attempt in range(3):
            if self.conn is None:
                self._connect()
            try:
                return fn(self.conn)
            except ftplib.error_perm:
                raise
            except Exception as e:  # noqa: BLE001
                self.ctx.log.warning("TX FTP error (%s), reconnecting", e)
                try:
                    self.conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self.conn = None
                time.sleep(2 ** attempt)
        raise RuntimeError("Texas FTP kept failing")

    def list(self, path: str) -> list[tuple[str, bool, str]]:
        """Return [(name, is_dir, timestamp)]."""
        lines: list[str] = []
        self._do(lambda c: (lines.clear(), c.retrlines(f"LIST {path}", lines.append)))
        out = []
        for line in lines:
            m = LIST_RE.match(line)
            if m:
                out.append((m.group(4), m.group(3) == "<DIR>", f"{m.group(1)} {m.group(2)}"))
        return out

    def read(self, path: str) -> bytes:
        buf = io.BytesIO()
        self._do(lambda c: (buf.seek(0), buf.truncate(), c.retrbinary(f"RETR {path}", buf.write)))
        return buf.getvalue()

    def close(self):
        if self.conn:
            try:
                self.conn.quit()
            except Exception:  # noqa: BLE001
                pass


def scrape(session: dict, ctx: Context) -> list[dict]:
    code = session["code"]
    store = ctx.cache.setdefault(f"files_{code}", {})   # path -> {"ts":..., "bill":...}
    stamp_key = f"listed_{code}"
    texts = ctx.cache.setdefault("text_cats", {})      # version url -> categories

    if not session.get("current") and store and time.time() - ctx.cache.get(stamp_key, 0) < OLD_SESSION_REFRESH:
        ctx.log.info("[TX %s] older session, using cached copy (%d bills)", code, len(store))
        return [_attach_text(v["bill"], texts) for v in store.values()]

    ftp = FTP(ctx)
    root = f"/bills/{code}/billhistory"
    try:
        try:
            type_dirs = {n for n, is_dir, _ in ftp.list(root) if is_dir}
        except ftplib.error_perm:
            raise SessionNotAvailable(code)
        if not type_dirs:
            raise SessionNotAvailable(code)

        live_paths = set()
        downloaded = 0
        for tdir in TYPE_DIRS:
            if tdir not in type_dirs:
                continue
            for group, is_dir, _ in ftp.list(f"{root}/{tdir}"):
                if not is_dir:
                    continue
                for fname, is_dir2, ts in ftp.list(f"{root}/{tdir}/{group}"):
                    if is_dir2 or not fname.lower().endswith(".xml"):
                        continue
                    path = f"{root}/{tdir}/{group}/{fname}"
                    live_paths.add(path)
                    if path in store and store[path]["ts"] == ts:
                        continue
                    if ctx.out_of_time():
                        continue
                    try:
                        bill = _parse(ftp.read(path), session)
                    except Exception as e:  # noqa: BLE001
                        ctx.warn(f"{path}: {e}")
                        continue
                    if bill:
                        store[path] = {"ts": ts, "bill": bill}
                        downloaded += 1
        for gone in set(store) - live_paths:
            store.pop(gone, None)
        if not ctx.out_of_time():
            ctx.cache[stamp_key] = time.time()
        ctx.log.info("[TX %s] %d bills, %d history files downloaded", code, len(store), downloaded)
    finally:
        ftp.close()

    bills = []
    for v in store.values():
        bill = v["bill"]
        if bill.get("text_url") and bill["text_url"] not in texts and not ctx.out_of_time():
            if ctx.screen(" ".join([bill["title"], " ".join(bill.get("subjects", []))])):
                texts[bill["text_url"]] = _text_categories(ctx, bill["text_url"])
        bills.append(_attach_text(bill, texts))
    return bills


def _attach_text(bill: dict, texts: dict) -> dict:
    b = dict(bill)
    cats = texts.get(b.get("text_url", ""))
    if cats:
        b["text_categories"] = cats
    return finalize(b)


def _text_categories(ctx: Context, url: str) -> dict:
    try:
        return ctx.classify(strip_html(ctx.client.get_text(url)))
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"text {url}: {e}")
        return {}


def _split(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split("|") if x.strip()]


def _parse(raw: bytes, session: dict) -> dict | None:
    root = ET.fromstring(raw.decode("utf-8-sig", errors="replace"))
    caption = (root.findtext("caption") or "").strip()
    if not caption or b"Bill does not exist" in raw:
        return None
    number = " ".join(root.attrib.get("bill", "").split(" ")[1:])   # "HB 1"
    prefix = number.split(" ")[0]
    kind = TYPE_NAMES.get(prefix[1:], "bill")
    code = session["code"]

    sponsors = [{"name": n, "role": "primary"} for n in _split(root.findtext("authors"))]
    sponsors += [{"name": n, "role": "cosponsor"} for n in _split(root.findtext("coauthors"))]
    sponsors += [{"name": n, "role": "sponsor"} for n in _split(root.findtext("sponsors"))]
    sponsors += [{"name": n, "role": "cosponsor"} for n in _split(root.findtext("cosponsors"))]

    actions = []
    for a in root.iterfind("actions/action"):
        num = a.findtext("actionNumber") or ""
        actions.append({
            "date": iso_date(a.findtext("date") or ""),
            "chamber": {"H": "House", "S": "Senate", "E": "Executive"}.get(num[:1], ""),
            "text": (a.findtext("description") or "").strip(),
        })

    text_url = ""
    for v in root.iterfind("billtext/docTypes/bill/versions/version"):
        u = v.findtext("WebHTMLURL")
        if u:
            text_url = u.replace("http://", "https://")

    return {
        "id": f"tx-{code}-{number.replace(' ', '')}",
        "state": "TX",
        "session": code,
        "session_name": session["name"],
        "number": number,
        "chamber": {"H": "House", "S": "Senate"}.get(prefix[:1], ""),
        "type": kind,
        "title": caption,
        "subjects": [re.sub(r"\s*\([A-Z]\d+\)\s*$", "", s.text or "").strip() for s in root.iterfind("subjects/subject")],
        "sponsors": sponsors,
        "actions": actions,
        "url": f"https://capitol.texas.gov/BillLookup/History.aspx?LegSess={code}&Bill={number.replace(' ', '')}",
        "text_url": text_url,
    }
