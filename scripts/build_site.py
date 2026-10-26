"""Assemble the static site in _site/: the app from site/, plus the data files."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"

if OUT.exists():
    shutil.rmtree(OUT)
shutil.copytree(ROOT / "site", OUT)
(OUT / "data").mkdir(exist_ok=True)
for name in ("meta.json", "health.json", "changes.json"):
    src = ROOT / "data" / name
    if src.exists():
        shutil.copy(src, OUT / "data" / name)
if (ROOT / "data" / "bills").exists():
    shutil.copytree(ROOT / "data" / "bills", OUT / "data" / "bills")
cat = ROOT / ".cache" / "catalog"
if cat.exists():
    shutil.copytree(cat, OUT / "data" / "catalog")
(OUT / ".nojekyll").write_text("")
print("site built:", sum(1 for _ in OUT.rglob("*") if _.is_file()), "files")
