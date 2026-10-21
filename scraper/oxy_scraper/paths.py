"""Where each pipeline step reads and writes. Everything under data/ is git-ignored."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # step 1: HTML exactly as served
PARSED_DIR = DATA_DIR / "parsed"  # step 2: one JSON per term, rows as listed
NORMALIZED_DIR = DATA_DIR / "normalized"  # step 3: courses/sections/professors to import
REPORTS_DIR = DATA_DIR / "reports"  # QA reports for manual review
OVERRIDES_DIR = REPO_ROOT / "scraper" / "overrides"  # committed, hand-maintained CSVs
