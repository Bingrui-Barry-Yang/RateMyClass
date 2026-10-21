from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
