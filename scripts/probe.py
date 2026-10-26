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
    # Minnesota (official XML API)
    "mn_search_xml": "https://www.revisor.mn.gov/bills/status_result.php?body=House&search=basic&session=0942025&location=House&bill=1-30&bill_type=bill&rev_number=&submit_bill=GO&keyword_type=all&keyword=&keyword_field_text=1&titleword=&format=xml",
    "mn_detail_xml": "https://api.revisor.mn.gov/bills/v1/94/2025/0/HF/10/",
    "mn_search_big": "https://www.revisor.mn.gov/bills/status_result.php?body=Senate&search=basic&session=0942025&location=Senate&bill=1-5000&bill_type=bill&rev_number=&submit_bill=GO&keyword_type=all&keyword=&keyword_field_text=1&titleword=&format=xml",
    # North Carolina
    "nc_bill": "https://www.ncleg.gov/BillLookUp/2025/H1246",
    "nc_feed_s": "https://www.ncleg.gov/Legislation/Bills/FiledBillsFeed/2025/S",
    # Wisconsin
    "wi_bill": "https://docs.legis.wisconsin.gov/2025/proposals/reg/asm/bill/ab89",
    "wi_feed": "https://docs.legis.wisconsin.gov/feed/2025/proposals",
    # Colorado
    "co_search": "https://leg.colorado.gov/bills/bill-search",
    "co_search_q": "https://leg.colorado.gov/bills/bill-search?session=2026A&page=1",
    "co_api_guess": "https://leg.colorado.gov/api/bills?session=2026A",
    # Michigan
    "mi_all": "https://legislature.mi.gov/Search/ExecuteSearch?chamber=&docTypesList=HB%2CSB&docTypesList=HJR%2CSJR&sessions=2025-2026&sponsor=&number=&dateFrom=&dateTo=&contentFullText=",
    "mi_bill": "https://legislature.mi.gov/Bills/Bill?ObjectName=2025-HB-4707",
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

# Georgia: the site's own API, with the token its web pages request
try:
    import hashlib, time as _t
    ts = str(int(_t.time() * 1000))
    key = hashlib.sha512(("QFpCwKfd7" + "fjVEXFFwSu36BwwcP83xYgxLAhLYmKk" + "letvarconst" + ts).encode()).hexdigest()
    tok = requests.get(f"https://www.legis.ga.gov/api/authentication/token?key={key}&ms={ts}", headers=UA, timeout=60).json()
    H = {**UA, "Authorization": "Bearer " + tok, "Content-Type": "application/json"}
    sess = requests.get("https://www.legis.ga.gov/api/sessions", headers=H, timeout=60)
    save("ga_sessions", sess.content, "txt")
    srch = requests.post("https://www.legis.ga.gov/api/Legislation/Search/20/0", json={"sessionId": 1033}, headers=H, timeout=60)
    save("ga_search", srch.content, "txt")
    try:
        lid = srch.json()["results"][0]["id"]
    except Exception:
        lid = None
    for nm, url in [("ga_detail", f"https://www.legis.ga.gov/api/legislation/detail/{lid}"),
                    ("ga_detail2", f"https://www.legis.ga.gov/api/Legislation/{lid}")]:
        rr = requests.get(url, headers=H, timeout=60)
        save(nm, rr.content, "txt")
        report[nm] = {"status": rr.status_code, "bytes": len(rr.content)}
    report["ga"] = {"token": bool(tok), "sessions": sess.status_code, "search": srch.status_code}
except Exception:
    report["ga"] = traceback.format_exc()

save("_report", json.dumps(report, indent=1), "json")
print(json.dumps(report, indent=1))
sys.exit(0)
