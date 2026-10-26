"""One-off probe: fetch sample responses from each state's data source so the
real formats can be inspected before scrapers are written. Output goes to
probe_out/ and is uploaded as a workflow artifact (not committed)."""

import ftplib
import json
import os
import sys
import traceback

import requests

OUT = "probe_out"
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; future-of-democracy-tracker/0.1; +https://github.com/MoveBeyondFPTP/Future-of-democracy)"}

URLS = {
    # Massachusetts
    "ma_courts": "https://malegislature.gov/api/GeneralCourts",
    "ma_docs_list": "https://malegislature.gov/api/GeneralCourts/194/Documents",
    "ma_doc_h1": "https://malegislature.gov/api/GeneralCourts/194/Documents/H1",
    "ma_doc_s1": "https://malegislature.gov/api/GeneralCourts/194/Documents/S1",
    "ma_doc_h1_history": "https://malegislature.gov/api/GeneralCourts/194/Documents/H1/DocumentHistoryActions",
    "ma_bill_html": "https://malegislature.gov/Bills/194/H1.Html",
    "ma_search": "https://malegislature.gov/Bills/Search?SearchTerms=%22ranked+choice%22&Page=1",
    # Virginia
    "va_bills_2026": "https://lis.blob.core.windows.net/lisfiles/20261/BILLS.CSV",
    "va_summaries_2026": "https://lis.blob.core.windows.net/lisfiles/20261/Summaries.csv",
    "va_history_2026": "https://lis.blob.core.windows.net/lisfiles/20261/HISTORY.CSV",
    "va_sponsors_2026": "https://lis.blob.core.windows.net/lisfiles/20261/Sponsors.csv",
    "va_bills_2027": "https://lis.blob.core.windows.net/lisfiles/20271/BILLS.CSV",
    # Maryland
    "md_json_2026": "https://mgaleg.maryland.gov/2026RS/misc/billsmasterlist/legislation.json",
    "md_json_2027": "https://mgaleg.maryland.gov/2027RS/misc/billsmasterlist/legislation.json",
    # Minnesota
    "mn_service": "https://www.revisor.mn.gov/bills/service.php",
    # North Carolina
    "nc_feed_h": "https://www.ncleg.gov/Legislation/Bills/FiledBillsFeed/2025/H",
    # Wisconsin
    "wi_list": "https://docs.legis.wisconsin.gov/2025/proposals/reg/asm/bill",
    # Colorado
    "co_bill": "https://leg.colorado.gov/bills/HB26-1362",
    # Michigan
    "mi_search": "https://legislature.mi.gov/Search/ExecuteSearch?chamber=&docTypesList=HB%2CSB&sessions=2025-2026&sponsor=&number=&dateFrom=&dateTo=&contentFullText=ranked+choice",
    # Georgia
    "ga_leg": "https://www.legis.ga.gov/legislation/all",
}


def save(name, data, ext):
    path = os.path.join(OUT, f"{name}.{ext}")
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as f:
        f.write(data)


report = {}
for name, url in URLS.items():
    try:
        r = requests.get(url, headers={**UA, "Accept": "application/json, text/html, */*"}, timeout=90)
        body = r.content
        report[name] = {"url": url, "status": r.status_code, "bytes": len(body),
                        "content_type": r.headers.get("content-type")}
        # keep at most 3 MB per sample
        save(name, body[:3_000_000], "txt")
    except Exception as e:  # noqa: BLE001
        report[name] = {"url": url, "error": repr(e)}

# Texas FTP
try:
    ftp = ftplib.FTP("ftp.legis.state.tx.us", timeout=60)
    ftp.login()
    listing = {}
    for d in ["/bills", "/bills/89R", "/bills/90R", "/bills/89R/billhistory",
              "/bills/89R/billhistory/house_bills", "/bills/89R/billhistory/house_bills/HB00001_HB00099"]:
        lines = []
        try:
            ftp.retrlines(f"LIST {d}", lines.append)
        except Exception as e:  # noqa: BLE001
            lines = [repr(e)]
        listing[d] = lines[:200]
    for fname in ["/bills/89R/billhistory/history.xml"]:
        buf = bytearray()
        try:
            ftp.retrbinary(f"RETR {fname}", buf.extend)
            save("tx_history_index", bytes(buf[:2_000_000]), "xml")
            report["tx_history_index"] = {"bytes": len(buf)}
        except Exception as e:  # noqa: BLE001
            report["tx_history_index"] = {"error": repr(e)}
    # one bill history file
    try:
        names = [l.split()[-1] if " " not in l.split(None, 3)[-1] else l.split(None, 3)[-1] for l in listing["/bills/89R/billhistory/house_bills/HB00001_HB00099"]]
        listing["_parsed_names"] = names[:10]
        lines = listing["/bills/89R/billhistory/house_bills/HB00001_HB00099"]
        first = lines[0].split(None, 3)[-1].strip() if lines else None
        if first:
            buf = bytearray()
            ftp.retrbinary(f"RETR /bills/89R/billhistory/house_bills/HB00001_HB00099/{first}", buf.extend)
            save("tx_bill_history_sample", bytes(buf), "xml")
    except Exception:  # noqa: BLE001
        listing["_sample_error"] = traceback.format_exc()
    ftp.quit()
    save("tx_ftp_listing", json.dumps(listing, indent=1), "json")
    report["tx_ftp"] = "ok"
except Exception:  # noqa: BLE001
    report["tx_ftp"] = traceback.format_exc()

save("_report", json.dumps(report, indent=1), "json")
print(json.dumps(report, indent=1))
sys.exit(0)
