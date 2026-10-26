"""Post this run's notable changes (newly found bills, status changes) as a
comment on a "Bill alerts" issue. GitHub emails repository owners about new
comments, so this works as free email alerts. Needs GITHUB_TOKEN and
GITHUB_REPOSITORY (both set automatically in GitHub Actions)."""

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TITLE = "Bill alerts"
SITE = os.environ.get("SITE_URL", "")


def main():
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GitHub token; skipping alerts.")
        return
    health = json.loads((ROOT / "data" / "health.json").read_text())
    stamps = {h.get("last_run") for h in health.values()}
    changes = json.loads((ROOT / "data" / "changes.json").read_text())
    events = [e for e in changes if e.get("seen") in stamps and e.get("kind") in ("new", "status")]
    if not events:
        print("No new alerts.")
        return
    meta = json.loads((ROOT / "data" / "meta.json").read_text())
    names = {c["key"]: c["name"] for c in meta["categories"]}

    lines = [f"**{len(events)} update{'s' if len(events) != 1 else ''}** on bills in your topics.\n"]
    by_cat = {}
    for e in events:
        for c in e.get("categories") or ["other"]:
            by_cat.setdefault(c, []).append(e)
    for c, evs in by_cat.items():
        lines.append(f"### {names.get(c, c)}")
        for e in evs[:40]:
            link = f"{SITE}#/bills?b={e['bill']}" if SITE else ""
            label = f"[{e['state']} {e['number']}]({link})" if link else f"{e['state']} {e['number']}"
            lines.append(f"- {label}: {e['text']}  \n  {e['title']}")
        if len(evs) > 40:
            lines.append(f"- …and {len(evs) - 40} more")
        lines.append("")
    body = "\n".join(lines)[:60000]

    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}"
    r = requests.get(f"{api}/issues", params={"state": "open", "labels": "bill-alerts", "per_page": 1}, headers=h, timeout=30)
    issues = r.json() if r.ok else []
    if issues:
        num = issues[0]["number"]
    else:
        r = requests.post(f"{api}/issues", headers=h, timeout=30, json={
            "title": TITLE, "labels": ["bill-alerts"],
            "body": "New bills and status changes in your tracked topics are posted here after each update. "
                    "GitHub emails you about each new comment (Watch this repository → Participating, or subscribe to this issue)."})
        if not r.ok:
            print("Could not create alerts issue:", r.status_code, r.text[:300])
            return
        num = r.json()["number"]
    r = requests.post(f"{api}/issues/{num}/comments", headers=h, json={"body": body}, timeout=30)
    print("Posted alerts:", r.status_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never fail the workflow over alerts
        print("Alert step failed:", e, file=sys.stderr)
