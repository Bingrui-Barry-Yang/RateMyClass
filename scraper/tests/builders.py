"""Small synthetic data/parsed term documents for normalize and load tests."""

from typing import Any

from oxy_scraper.exclusions import Exclusion
from oxy_scraper.normalize import Normalizer, Result
from oxy_scraper.overrides import Overrides
from oxy_scraper.parse import CODE_RE

EXCLUSIONS = [Exclusion("title_contains", "Credit by Exam", "credit by exam")]
WALSH = ("Joel Anderson Walsh", "Walsh,J")
MWF = [("10:40am-11:35am", "MWF")]


class Term:
    """Builds one data/parsed/<term>.json document."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.sections: list[dict[str, Any]] = []
        self.details: dict[str, dict[str, Any]] = {}

    def add(
        self,
        crn: str,
        code: str,
        title: str,
        *,
        profs: tuple[tuple[str, str], ...] = (WALSH,),
        meetings: list[tuple[str, str]] = MWF,
        description: str | None = None,
        restrictions: tuple[str, ...] = (),
    ) -> "Term":
        m = CODE_RE.match(code)
        assert m
        self.sections.append(
            {
                "crn": crn,
                "subject": m["dept"],
                "code_raw": code,
                "dept": m["dept"],
                "number": m["number"],
                "section": m["section"],
                "lab_section": m["lab"],
                "title": title,
                "units": 0 if m["lab"] else 4,
                "instructors": [{"full": f, "short": s} for f, s in profs],
                "meetings": [{"time": t, "days": d} for t, d in meetings],
                "core": [],
                "seats": {},
                "detail_crn": crn if description else None,
                "detail_shared": False,
            }
        )
        if description:
            self.details[crn] = {
                "crn": crn,
                "description": description,
                "restrictions": list(restrictions),
                "prerequisites": [],
                "corequisites": None,
                "reserved_seats": [],
            }
        return self

    def doc(self) -> dict[str, Any]:
        return {
            "term": self.code,
            "term_label": "",
            "subjects": {s["dept"]: s["dept"].title() for s in self.sections},
            "sections": self.sections,
            "details": self.details,
        }


def run(*terms: Term, overrides: Overrides | None = None) -> Result:
    return Normalizer([t.doc() for t in terms], EXCLUSIONS, overrides or Overrides()).run()


def courses(result: Result) -> dict[str, dict[str, Any]]:
    return {c["key"]: c for c in result.courses}


def sections(result: Result) -> dict[tuple[str, str], dict[str, Any]]:
    return {(s["term"], s["code_raw"]): s for s in result.sections}
