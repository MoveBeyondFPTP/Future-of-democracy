"""Collect bills from every enabled state, classify them, and write:

  data/bills/<ST>.json   full records for bills in any category (committed)
  data/changes.json      recent activity feed on those bills (committed)
  data/health.json       per-state run status (committed)
  data/meta.json         categories, states and labels for the app (committed)
  .cache/catalog/<ST>.json  compact list of *every* bill, for app-wide search
                            (published with the site, not committed)

Usage:  python -m tracker.run [--states MA,TX]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import logging
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .classify import CATEGORIES_PATH, load_categories, merge
from .http import Client
from .model import STATUS_LABELS, STATUSES, classification_text
from .sources.base import Context, SessionNotAvailable

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / ".cache"
STATES_PATH = ROOT / "config" / "states.yml"
MAX_CHANGES = 2000
BAN_WORDS = re.compile(r"prohibit|\bban(s|ned|ning)?\b|repeal|may not|shall not|preclud", re.I)

log = logging.getLogger("tracker")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default):
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt") as f:
                return json.load(f)
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, obj, compact: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        with gzip.open(path, "wt") as f:
            json.dump(obj, f, separators=(",", ":"))
        return
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) if compact else \
        json.dumps(obj, indent=1, ensure_ascii=False)
    path.write_text(text + "\n")


def catalog_row(b: dict) -> list:
    cats = ",".join(f"{k}:{'m' if v['level'] == 'match' else 'p'}" for k, v in b.get("categories", {}).items())
    return [
        b["id"], b["number"], b["session"], b["title"][:300],
        STATUSES.index(b["status"]) if b["status"] in STATUSES else 0,
        b.get("last_action_date", ""), cats, b.get("url", ""),
    ]


def slim(b: dict) -> dict:
    """Record as stored in data/bills: drop internal fields."""
    out = {k: v for k, v in b.items() if not k.startswith("_") and k != "text_categories"}
    return out


def diff_events(state: str, old: dict, new: dict, stamp: str) -> list[dict]:
    events = []
    for bid, b in new.items():
        o = old.get(bid)
        base = {"bill": bid, "state": state, "number": b["number"], "title": b["title"][:200],
                "categories": sorted(b.get("categories", {})), "seen": stamp}
        if not o:
            events.append({**base, "kind": "new", "date": b.get("last_action_date") or b.get("introduced", ""),
                           "text": "Now tracked: " + (b.get("last_action") or "filed")})
            continue
        old_actions = {(a["date"], a["text"]) for a in o.get("actions", [])}
        for a in b.get("actions", []):
            if (a["date"], a["text"]) not in old_actions:
                events.append({**base, "kind": "action", "date": a["date"], "text": a["text"]})
        if o.get("status") != b.get("status"):
            events.append({**base, "kind": "status", "date": b.get("last_action_date", ""),
                           "text": f"Status: {STATUS_LABELS.get(o.get('status'), o.get('status'))} → "
                                   f"{STATUS_LABELS.get(b['status'], b['status'])}"})
        new_cats = set(b.get("categories", {})) - set(o.get("categories", {}))
        if new_cats:
            events.append({**base, "kind": "category", "date": b.get("last_action_date", ""),
                           "text": "Added to: " + ", ".join(sorted(new_cats))})
    return events


def run_state(code: str, cfg: dict, categories, cat_hash: str) -> dict:
    src = importlib.import_module(f"tracker.sources.{cfg['source']}")
    cache_path = CACHE / f"{code}.json.gz"
    cache = read_json(cache_path, {})
    if cache.get("_cat_hash") != cat_hash:
        # Categories changed: forget cached classifications so everything is re-read.
        for k in list(cache):
            if k == "text_cats" or k.startswith("details_"):
                cache.pop(k)
        cache["_cat_hash"] = cat_hash

    ctx = Context(state=code, categories=categories, cache=cache, client=Client(delay=cfg.get("delay", 0.25)))
    report = {"sessions": {}, "warnings": [], "started": now_iso()}
    all_bills, ok_sessions = [], 0

    for sess in cfg.get("sessions", []):
        t0 = time.time()
        try:
            bills = src.scrape(sess, ctx)
            for b in bills:
                lead = f"{b.get('title', '')}. {(b.get('summary') or '')[:300]}"
                cats = ctx.classify(classification_text(b), lead)
                text_cats = b.pop("text_categories", {}) or {}
                merged = merge(cats, text_cats)
                # Sub-tags from the title/summary win over ones found deep in bill text.
                for k, v in merged.items():
                    if cats.get(k, {}).get("subtags"):
                        v["subtags"] = cats[k]["subtags"]
                    tags = v.get("subtags", [])
                    if "ban" in tags and "adoption" in tags:
                        # A bill rarely does both; the title/summary decides.
                        drop = "adoption" if BAN_WORDS.search(lead) else "ban"
                        v["subtags"] = [t for t in tags if t != drop]
                b["categories"] = merged
            all_bills.extend(bills)
            ok_sessions += 1
            report["sessions"][sess["code"]] = {"bills": len(bills), "seconds": round(time.time() - t0)}
        except SessionNotAvailable:
            ok_sessions += 1
            report["sessions"][sess["code"]] = {"bills": 0, "note": "not published yet"}
        except Exception as e:  # noqa: BLE001
            log.error("[%s %s] failed: %s", code, sess["code"], traceback.format_exc())
            report["sessions"][sess["code"]] = {"error": f"{type(e).__name__}: {e}"[:500]}

    write_json(cache_path, cache)
    report["warnings"] = ctx.warnings
    report["requests"] = ctx.client.count
    report["ok"] = ok_sessions == len(cfg.get("sessions", [])) and ok_sessions > 0
    return {"bills": all_bills, "report": report}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", help="comma-separated state codes (default: all enabled)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    states_cfg = yaml.safe_load(STATES_PATH.read_text())["states"]
    categories = load_categories()
    cat_hash = hashlib.sha256(CATEGORIES_PATH.read_bytes()).hexdigest()[:16]
    wanted = {s.strip().upper() for s in args.states.split(",")} if args.states else None

    health = read_json(DATA / "health.json", {})
    changes = read_json(DATA / "changes.json", [])
    stamp = now_iso()
    any_error = False

    for code, cfg in states_cfg.items():
        if not cfg.get("enabled") or (wanted and code not in wanted):
            continue
        log.info("=== %s", code)
        result = run_state(code, cfg, categories, cat_hash)
        rep = result["report"]
        bills = result["bills"]
        prev = health.get(code, {})
        out_path = DATA / "bills" / f"{code}.json"
        old = {b["id"]: b for b in read_json(out_path, {}).get("bills", [])}

        relevant = {b["id"]: slim(b) for b in bills if b.get("categories")}
        # Sessions that errored this run: carry over their previously saved bills.
        failed_sessions = {s for s, r in rep["sessions"].items() if "error" in r}
        for bid, b in old.items():
            if b.get("session") in failed_sessions and bid not in relevant:
                relevant[bid] = b

        if bills or not old:
            events = diff_events(code, old, relevant, stamp) if old else []
            changes = events + changes
            ordered = sorted(relevant.values(), key=lambda b: (b.get("last_action_date", ""), b["id"]), reverse=True)
            write_json(out_path, {"state": code, "name": cfg["name"], "generated": stamp, "bills": ordered})
            if bills:
                catalog = [catalog_row(b) for b in bills]
                write_json(CACHE / "catalog" / f"{code}.json", {"state": code, "generated": stamp, "rows": catalog}, compact=True)

        health[code] = {
            "name": cfg["name"],
            "last_run": stamp,
            "last_success": stamp if rep["ok"] else prev.get("last_success"),
            "ok": rep["ok"],
            "bills_total": len(bills) if bills else prev.get("bills_total", 0),
            "tracked": len(relevant),
            "sessions": rep["sessions"],
            "requests": rep["requests"],
            "warnings": rep["warnings"][:20],
        }
        any_error |= not rep["ok"]
        log.info("[%s] done: %d bills, %d in categories, ok=%s", code, len(bills), len(relevant), rep["ok"])

    changes.sort(key=lambda e: (e.get("date", ""), e.get("seen", "")), reverse=True)
    write_json(DATA / "changes.json", changes[:MAX_CHANGES])
    write_json(DATA / "health.json", health)
    write_meta(states_cfg)
    return 0


def write_meta(states_cfg: dict):
    raw = yaml.safe_load(CATEGORIES_PATH.read_text())["categories"]
    meta = {
        "generated": now_iso(),
        "categories": [
            {"key": k, "name": v.get("name", k), "description": (v.get("description") or "").strip(),
             "subtags": list((v.get("subtags") or {}).keys())}
            for k, v in raw.items()
        ],
        "states": {
            code: {"name": c["name"], "enabled": bool(c.get("enabled")),
                   "sessions": [{"code": s["code"], "name": s["name"], "current": bool(s.get("current"))}
                                for s in c.get("sessions", [])]}
            for code, c in states_cfg.items()
        },
        "statuses": [{"key": s, "label": STATUS_LABELS[s]} for s in STATUSES],
    }
    write_json(DATA / "meta.json", meta)


if __name__ == "__main__":
    sys.exit(main())
