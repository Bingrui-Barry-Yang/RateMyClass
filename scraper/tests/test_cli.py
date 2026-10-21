from pathlib import Path

import pytest

from oxy_scraper import paths
from oxy_scraper.cli import main


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: oxy_scraper" in capsys.readouterr().out


def test_data_dirs_live_under_repo_root() -> None:
    assert (paths.REPO_ROOT / "scraper" / "oxy_scraper").is_dir()
    assert paths.RAW_DIR.relative_to(paths.REPO_ROOT).as_posix() == "data/raw"


def test_parse_unknown_term_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "RAW_DIR", tmp_path)
    assert main(["parse", "--terms", "209901"]) == 2
