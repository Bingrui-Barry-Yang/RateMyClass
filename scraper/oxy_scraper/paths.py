"""Where each pipeline step reads and writes. Everything under data/ is git-ignored."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# OXY_DATA_DIR points the whole pipeline at another folder (e.g. a fresh scrape to compare with).
DATA_DIR = Path(os.environ.get("OXY_DATA_DIR") or REPO_ROOT / "data")
RAW_DIR = DATA_DIR / "raw"  # step 1: HTML exactly as served
STAGING_DIR = RAW_DIR / ".staging"  # `update` downloads here, swapped into raw/ when complete
PARSED_DIR = DATA_DIR / "parsed"  # step 2: one JSON per term, rows as listed
NORMALIZED_DIR = DATA_DIR / "normalized"  # step 3: courses/sections/professors to import
REPORTS_DIR = DATA_DIR / "reports"  # QA reports for manual review
OVERRIDES_DIR = REPO_ROOT / "scraper" / "overrides"  # committed, hand-maintained CSVs
