"""
One-off patch to backfill wholesale + affiliates sections into existing
data/YYYY-MM.json files without regenerating meta/google/klaviyo/shopify.

Safe to re-run. Does NOT commit to git.

Usage:
    python patch_backfill.py              # patch all months in manifest
    python patch_backfill.py 2026-04      # patch only one month
"""

import json
import logging
import sys
from pathlib import Path

from extract import extract_wholesale, extract_affiliates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("patch_backfill")

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"


def patch_month(month: str) -> None:
    path = DATA_DIR / f"{month}.json"
    if not path.exists():
        log.warning("Skip %s: file not found", month)
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    log.info("Patching %s (existing keys: %s)", month, list(data.keys()))

    try:
        data["wholesale"] = extract_wholesale(month)
    except Exception as exc:
        log.exception("wholesale failed for %s: %s", month, exc)
        data.setdefault("wholesale", {"totals": {}, "daily": [], "pipeline": [], "top_accounts": []})

    try:
        data["affiliates"] = extract_affiliates(month)
    except Exception as exc:
        log.exception("affiliates failed for %s: %s", month, exc)
        data.setdefault("affiliates", {"totals": {}, "daily": [], "top_affiliates": []})

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    w = data["wholesale"]["totals"]
    a = data["affiliates"]["totals"]
    log.info(
        "  wholesale: %d orders, €%.0f | affiliates: %d orders, €%.0f",
        w.get("orders", 0), w.get("revenue", 0),
        a.get("orders", 0), a.get("revenue", 0),
    )


def main():
    if len(sys.argv) > 1:
        months = sys.argv[1:]
    else:
        manifest = json.loads((DATA_DIR / "manifest.json").read_text())
        months = manifest.get("months", [])

    for m in months:
        patch_month(m)


if __name__ == "__main__":
    main()
