"""HTML -> Python data for counts.oxy.edu pages. Pure functions, no network."""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

# "COMP 131 1-2" -> dept, number, section, lab section. Numbers may carry a suffix ("BIO 224L").
CODE_RE = re.compile(r"^(?P<dept>[A-Z]+) (?P<number>\w+) (?P<section>\w+)(?:-(?P<lab>\w+))?$")
POSTBACK_RE = re.compile(r"__doPostBack\('([^']+)'")


@dataclass(frozen=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True)
class Instructor:
    full: str  # "Hector Miguel Camarillo Abad" (abbr title)
    short: str  # "Camarillo Abad,H" (link text: last name before the comma)


@dataclass
class ListRow:
    crn: str
    event_target: str  # postback target that opens this row's detail popup
    code_raw: str
    dept: str | None
    number: str | None
    section: str | None
    lab_section: str | None
    title: str
    units: str
    instructors: list[Instructor] = field(default_factory=list)
    meetings: list[list[str]] = field(default_factory=list)  # each: [time, days, ...]
    core: list[Option] = field(default_factory=list)
    seats: list[str] = field(default_factory=list)  # max, enrolled, reserved, open, waitlist

    @property
    def is_dash_lab(self) -> bool:
        """A lab listed under a lecture section ("COMP 131 1-1")."""
        return self.lab_section is not None


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def hidden_fields(doc: BeautifulSoup) -> dict[str, str]:
    """The WebForms state (__VIEWSTATE, __EVENTVALIDATION, ...) every postback must echo."""
    fields = {}
    for tag in doc.find_all("input", attrs={"type": "hidden"}):
        name = tag.get("name")
        if isinstance(name, str):
            value = tag.get("value", "")
            fields[name] = value if isinstance(value, str) else ""
    return fields


def select_options(doc: BeautifulSoup, name_suffix: str) -> list[Option]:
    select = doc.find("select", attrs={"name": re.compile(re.escape(name_suffix) + "$")})
    if not isinstance(select, Tag):
        raise ValueError(f"no <select> named *{name_suffix} on page")
    return [
        Option(str(opt.get("value", "")), opt.get_text(strip=True))
        for opt in select.find_all("option")
    ]


def _rows(table: Tag) -> list[Tag]:
    body = table.find("tbody", recursive=False)
    parent = body if isinstance(body, Tag) else table
    return [tr for tr in parent.find_all("tr", recursive=False) if isinstance(tr, Tag)]


def _cells(tr: Tag) -> list[Tag]:
    return [td for td in tr.find_all("td", recursive=False) if isinstance(td, Tag)]


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _abbrs(cell: Tag) -> list[tuple[str, str]]:
    return [(str(a.get("title", "")).strip(), _text(a)) for a in cell.find_all("abbr")]


def parse_list(doc: BeautifulSoup) -> list[ListRow]:
    """Rows of the results grid (#gvResults). An absent grid means no sections."""
    table = doc.find("table", id="gvResults")
    if not isinstance(table, Tag):
        return []
    rows = []
    for tr in _rows(table):
        cells = _cells(tr)
        link = cells[0].find("a") if cells else None
        if not isinstance(link, Tag):  # header row
            continue
        target = POSTBACK_RE.search(str(link.get("href", "")))
        code_raw = _text(cells[1])
        code = CODE_RE.match(code_raw)
        rows.append(
            ListRow(
                crn=_text(link),
                event_target=target.group(1) if target else "",
                code_raw=code_raw,
                dept=code["dept"] if code else None,
                number=code["number"] if code else None,
                section=code["section"] if code else None,
                lab_section=code["lab"] if code else None,
                title=_text(cells[2]),
                units=_text(cells[3]),
                instructors=[Instructor(full, short) for full, short in _abbrs(cells[4])],
                meetings=[
                    [_text(td) for td in _cells(mtr)]
                    for mtr in cells[5].find_all("tr")
                    if isinstance(mtr, Tag) and _text(mtr)
                ],
                core=[Option(code, name) for name, code in _abbrs(cells[6])],
                seats=[_text(td) for td in cells[7:]],
            )
        )
    return rows


def detail_crn(doc: BeautifulSoup) -> str | None:
    """CRN shown in the detail popup (#gvDetails), or None if the page has no popup."""
    table = doc.find("table", id="gvDetails")
    if not isinstance(table, Tag):
        return None
    for tr in _rows(table):
        cells = _cells(tr)
        if cells:
            return _text(cells[0])
    return None


def detail_description(doc: BeautifulSoup) -> str | None:
    """Course description in the detail popup (#lblCrseDesc)."""
    span = doc.find("span", id="lblCrseDesc")
    return _text(span) if isinstance(span, Tag) else None
