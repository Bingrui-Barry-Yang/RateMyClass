import datetime
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.review import REVIEW_EMPHASES
from app.schemas.reviews import Emphasis, EmphasisCounts

from .factories import Factory

FALL, SPRING = "202601", "202602"
GROUP = "202602:AMST 329 1+BLST 329 1"


def day(month: int, d: int) -> datetime.date:
    return datetime.date(2026, month, d)


@pytest.fixture
def world(db: Session) -> dict[str, int]:
    """COMP 131 (lecture, two labs, a co-taught spring lecture), AMST/BLST 329 cross-listed,
    PHYS 206 renumbered from 266 and PHYS 100 without reviews. Returns review ids."""
    f = Factory(db)
    walsh, lee, zhang = f.professor("walsh-joel"), f.professor("lee-ann"), f.professor("zhang-mei")
    smith, park = f.professor("smith-kim"), f.professor("park-jun")

    comp = f.course("COMP-131", "Fundamentals of Computer Science")
    lecture = f.section(comp, FALL, "1001", "COMP 131 1", [walsh])
    lee_lab = f.section(comp, FALL, "1002", "COMP 131 1-1", [lee])  # lee teaches only a lab
    walsh_lab = f.section(comp, FALL, "1003", "COMP 131 1-2", [walsh])
    spring = f.section(comp, SPRING, "2001", "COMP 131 1", [walsh, zhang])

    amst = f.course("AMST-329", "Race and Film")
    blst = f.course("BLST-329", "Race and Film")
    amst_sec = f.section(amst, SPRING, "2100", "AMST 329 1", [smith], cross_list_group=GROUP)
    blst_sec = f.section(blst, SPRING, "2101", "BLST 329 1", [smith], cross_list_group=GROUP)

    old = f.course("PHYS-100", "Physics Before")
    f.section(old, FALL, "1200", "PHYS 100 1", [park])
    phys = f.course(
        "PHYS-206",
        "Modern Physics",
        numbers=[{"number": "266", "terms": [FALL]}, {"number": "206", "terms": [SPRING]}],
        related=[
            {"key": "PHYS-100", "relation": "formerly"},
            {"key": "PHYS-999", "relation": "see_also"},  # no longer exists
        ],
    )
    f.section(phys, FALL, "1201", "PHYS 266 1")
    f.section(phys, SPRING, "2201", "PHYS 206 1")

    reviews = {
        # One review about Walsh's lecture and lab: counts once.
        "walsh": f.review(
            [(lecture, walsh), (walsh_lab, walsh)],
            day(1, 10),
            overall=8,
            difficulty=6,
            workload=7,
            emphasis=["exam", "project"],
        ),
        "lee": f.review(
            [(lee_lab, lee)],
            day(1, 12),
            overall=6,
            difficulty=4,
            workload=5,
            take_course_again=False,
            emphasis=["participation"],
        ),
        "zhang": f.review(
            [(spring, zhang)],
            day(5, 20),
            overall=9,
            difficulty=8,
            workload=9,
            take_prof_again=False,
            emphasis=["exam"],
        ),
        "blst": f.review([(blst_sec, smith)], day(5, 21), overall=7, emphasis=["paper"]),
        "amst": f.review([(amst_sec, smith)], day(5, 22), overall=5),
    }
    db.flush()
    return {name: r.id for name, r in reviews.items()}


def ids(page: dict[str, Any]) -> list[int]:
    return [r["id"] for r in page["items"]]


def no_reviews() -> dict[str, Any]:
    return {
        "count": 0,
        "avg_overall": None,
        "avg_difficulty": None,
        "avg_workload": None,
        "take_course_again_pct": None,
        "take_prof_again_pct": None,
        "emphasis_counts": dict.fromkeys(REVIEW_EMPHASES, 0),
    }


def test_emphasis_types_match_the_table() -> None:
    assert get_args(Emphasis) == REVIEW_EMPHASES
    assert tuple(EmphasisCounts.model_fields) == REVIEW_EMPHASES


def test_departments(api: TestClient, world: dict[str, int]) -> None:
    resp = api.get("/api/departments")
    assert resp.status_code == 200
    assert {d["code"]: (d["course_count"], d["professor_count"]) for d in resp.json()} == {
        "AMST": (1, 1),
        "BLST": (1, 1),
        "COMP": (1, 3),
        "PHYS": (2, 1),
    }
    assert [d["code"] for d in resp.json()] == ["AMST", "BLST", "COMP", "PHYS"]


def test_department_courses(api: TestClient, world: dict[str, int]) -> None:
    comp = api.get("/api/departments/COMP/courses").json()
    assert comp == [
        {
            "key": "COMP-131",
            "number": "131",
            "title": "Fundamentals of Computer Science",
            "is_topic": False,
            "last_term": {"code": SPRING, "label": "2026 Spring"},
            "review_count": 3,
            "avg_overall": 7.7,
        }
    ]
    phys = api.get("/api/departments/PHYS/courses").json()
    assert [(c["key"], c["review_count"], c["avg_overall"]) for c in phys] == [
        ("PHYS-100", 0, None),
        ("PHYS-206", 0, None),
    ]
    blst = api.get("/api/departments/BLST/courses").json()
    assert blst[0]["review_count"] == 2  # includes the AMST listing's review


def test_department_professors(api: TestClient, world: dict[str, int]) -> None:
    comp = api.get("/api/departments/COMP/professors").json()
    assert [(p["key"], p["review_count"], p["avg_overall"]) for p in comp] == [
        ("lee-ann", 1, 6.0),
        ("walsh-joel", 1, 8.0),
        ("zhang-mei", 1, 9.0),
    ]
    assert comp[0]["display_name"] == "Ann Lee"


@pytest.mark.parametrize(
    "path",
    [
        "/api/departments/NOPE/courses",
        "/api/departments/NOPE/professors",
        "/api/courses/NOPE-1",
        "/api/courses/NOPE-1/reviews",
        "/api/courses/COMP-131/reviews?professor=nobody-here",
        "/api/courses/COMP-131/reviews?term=209901",
        "/api/professors/nobody-here",
        "/api/professors/nobody-here/reviews",
        "/api/professors/walsh-joel/reviews?course=NOPE-1",
    ],
)
def test_unknown_keys_are_404(api: TestClient, world: dict[str, int], path: str) -> None:
    resp = api.get(path)
    assert resp.status_code == 404
    assert resp.json()["detail"].startswith("No ")


def test_course_detail(api: TestClient, world: dict[str, int]) -> None:
    course = api.get("/api/courses/COMP-131").json()
    assert course["dept"] == {"code": "COMP", "name": "COMP Department"}
    assert [t["code"] for t in course["terms"]] == [FALL, SPRING]
    # Lab-only professors are listed too, by last name, each with their terms.
    assert [(p["key"], [t["code"] for t in p["terms"]]) for p in course["professors"]] == [
        ("lee-ann", [FALL]),
        ("walsh-joel", [FALL, SPRING]),
        ("zhang-mei", [SPRING]),
    ]
    assert course["cross_listed"] == [] and course["related"] == []
    assert course["summary"] == {
        "count": 3,
        "avg_overall": 7.7,
        "avg_difficulty": 6.0,
        "avg_workload": 7.0,
        "take_course_again_pct": 67,
        "take_prof_again_pct": 67,
        "emphasis_counts": {
            "exam": 2,
            "participation": 1,
            "paper": 0,
            "presentation": 0,
            "project": 1,
        },
    }


def test_course_detail_links_and_numbers(api: TestClient, world: dict[str, int]) -> None:
    phys = api.get("/api/courses/PHYS-206").json()
    formerly = {"key": "PHYS-100", "title": "Physics Before", "relation": "formerly"}
    assert phys["related"] == [formerly]  # the link to a deleted course is left out
    assert [n["number"] for n in phys["numbers"]] == ["266", "206"]
    assert [t["code"] for t in phys["terms"]] == [FALL, SPRING]
    assert phys["professors"] == []
    assert phys["summary"] == no_reviews()

    amst = api.get("/api/courses/AMST-329").json()
    assert amst["cross_listed"] == [
        {
            "key": "BLST-329",
            "dept": "BLST",
            "number": "329",
            "title": "Race and Film",
            "terms": [{"code": SPRING, "label": "2026 Spring"}],
        }
    ]


def test_cross_listed_courses_share_reviews(api: TestClient, world: dict[str, int]) -> None:
    amst = api.get("/api/courses/AMST-329/reviews").json()
    blst = api.get("/api/courses/BLST-329/reviews").json()
    assert ids(amst) == ids(blst) == [world["amst"], world["blst"]]
    assert amst["summary"] == blst["summary"]
    assert amst["summary"]["count"] == 2 and amst["summary"]["avg_overall"] == 6.0


def test_course_reviews_newest_first_with_targets(api: TestClient, world: dict[str, int]) -> None:
    page = api.get("/api/courses/COMP-131/reviews").json()
    assert ids(page) == [world["zhang"], world["lee"], world["walsh"]]
    assert page["total"] == 3 and page["limit"] == 20 and page["offset"] == 0
    walsh = page["items"][2]
    assert [t["code"] for t in walsh["targets"]] == ["COMP 131 1", "COMP 131 1-2"]
    assert walsh["targets"][0] == {
        "term": FALL,
        "term_label": "2025 Fall",
        "crn": "1001",
        "code": "COMP 131 1",
        "kind": "lecture",
        "course_key": "COMP-131",
        "course_title": "Fundamentals of Computer Science",
        "professor_key": "walsh-joel",
        "professor_name": "Joel Walsh",
    }
    assert walsh["emphasis"] == ["exam", "project"]
    assert walsh["created_on"] == "2026-01-10" and walsh["comment"] == "Sample review."


def test_course_reviews_filtered_with_the_summary(api: TestClient, world: dict[str, int]) -> None:
    walsh = api.get("/api/courses/COMP-131/reviews?professor=walsh-joel").json()
    assert ids(walsh) == [world["walsh"]]
    assert walsh["summary"]["count"] == 1 and walsh["summary"]["avg_overall"] == 8.0

    spring = api.get(f"/api/courses/COMP-131/reviews?term={SPRING}").json()
    assert ids(spring) == [world["zhang"]]
    assert spring["summary"]["take_prof_again_pct"] == 0

    # Walsh co-taught the spring lecture, but the spring review is about Zhang.
    both = api.get(f"/api/courses/COMP-131/reviews?professor=walsh-joel&term={SPRING}").json()
    assert both["items"] == [] and both["total"] == 0 and both["summary"] == no_reviews()


def test_pagination(api: TestClient, world: dict[str, int]) -> None:
    first = api.get("/api/courses/COMP-131/reviews?limit=2").json()
    rest = api.get("/api/courses/COMP-131/reviews?limit=2&offset=2").json()
    assert ids(first) == [world["zhang"], world["lee"]]
    assert ids(rest) == [world["walsh"]]
    assert first["total"] == rest["total"] == 3
    assert rest["summary"]["count"] == 3  # the summary covers every page
    assert api.get("/api/courses/COMP-131/reviews?limit=101").status_code == 422
    assert api.get("/api/courses/COMP-131/reviews?offset=-1").status_code == 422


def test_professor_detail(api: TestClient, world: dict[str, int]) -> None:
    walsh = api.get("/api/professors/walsh-joel").json()
    assert walsh["display_name"] == "Joel Walsh"
    assert walsh["departments"] == [{"code": "COMP", "name": "COMP Department"}]
    assert [(c["key"], [t["code"] for t in c["terms"]]) for c in walsh["courses"]] == [
        ("COMP-131", [FALL, SPRING])
    ]
    assert walsh["summary"]["count"] == 1  # lecture + lab review counts once

    smith = api.get("/api/professors/smith-kim").json()
    assert [c["key"] for c in smith["courses"]] == ["AMST-329", "BLST-329"]
    assert [d["code"] for d in smith["departments"]] == ["AMST", "BLST"]

    park = api.get("/api/professors/park-jun").json()  # no reviews is still a page
    assert park["summary"] == no_reviews()


def test_professor_reviews(api: TestClient, world: dict[str, int]) -> None:
    smith = api.get("/api/professors/smith-kim/reviews").json()
    assert ids(smith) == [world["amst"], world["blst"]]

    # The course filter includes the cross-listed copy, and the summary follows it.
    amst = api.get("/api/professors/smith-kim/reviews?course=AMST-329").json()
    assert ids(amst) == [world["amst"], world["blst"]]
    other = api.get("/api/professors/smith-kim/reviews?course=COMP-131").json()
    assert other["items"] == [] and other["summary"] == no_reviews()

    walsh = api.get(f"/api/professors/walsh-joel/reviews?term={FALL}").json()
    assert ids(walsh) == [world["walsh"]] and walsh["total"] == 1


def test_course_list(api: TestClient, world: dict[str, int]) -> None:
    courses = api.get("/api/courses").json()
    assert [c["key"] for c in courses] == [
        "AMST-329",
        "BLST-329",
        "COMP-131",
        "PHYS-100",
        "PHYS-206",
    ]
    assert courses[-1] == {
        "key": "PHYS-206",
        "dept": "PHYS",
        "number": "206",
        "title": "Modern Physics",
        "former_numbers": ["266"],  # "PHYS 266" can find it
    }
    assert courses[2]["former_numbers"] == []


def test_professor_list(api: TestClient, world: dict[str, int]) -> None:
    professors = api.get("/api/professors").json()
    assert [(p["key"], p["departments"]) for p in professors] == [
        ("lee-ann", ["COMP"]),  # taught only a lab
        ("park-jun", ["PHYS"]),
        ("smith-kim", ["AMST", "BLST"]),
        ("walsh-joel", ["COMP"]),
        ("zhang-mei", ["COMP"]),
    ]
    assert professors[0]["display_name"] == "Ann Lee"


@pytest.mark.parametrize("path", ["/api/departments", "/api/courses", "/api/professors"])
def test_lists_are_not_sent_again_when_unchanged(
    api: TestClient, db: Session, world: dict[str, int], path: str
) -> None:
    first = api.get(path)
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"

    again = api.get(path, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == etag
    weak = api.get(path, headers={"If-None-Match": f"W/{etag}"})
    assert weak.status_code == 304

    # An import changes the data, so the old ETag no longer matches.
    f = Factory(db)
    f.section(f.course("ZOOL-101"), FALL, "1999", "ZOOL 101 1", [f.professor("new-person")])
    db.flush()
    changed = api.get(path, headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag


def test_large_responses_are_gzipped(api: TestClient, db: Session) -> None:
    f = Factory(db)
    for n in range(100, 140):
        f.course(f"COMP-{n}", f"A long enough course title number {n}")
    db.flush()
    big = api.get("/api/courses", headers={"Accept-Encoding": "gzip"})
    assert big.headers["content-encoding"] == "gzip"
    assert len(big.json()) == 40  # the client decompresses it
    small = api.get("/api/departments", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers
