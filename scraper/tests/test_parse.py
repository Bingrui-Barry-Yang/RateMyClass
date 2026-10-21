from oxy_scraper.parse import (
    Prerequisite,
    ReservedSeats,
    detail_crn,
    detail_description,
    hidden_fields,
    parse_detail,
    parse_list,
    select_options,
    soup,
)

from .conftest import fixture_html


def test_term_dropdown_lists_all_terms() -> None:
    terms = select_options(soup(fixture_html("home.html")), "ddlSemesters")
    assert len(terms) == 20
    assert terms[0].value == "202101"
    assert terms[0].label == "2020 Fall Semester"


def test_summer_term_offers_only_its_own_subjects() -> None:
    subjects = select_options(soup(fixture_html("term_202603.html")), "ddlSubjects")
    assert [s.value for s in subjects if s.value] == ["CWP", "CSLC", "CORE", "ENGL", "KINE", "MAC"]


def test_hidden_fields_carry_page_state() -> None:
    fields = hidden_fields(soup(fixture_html("list_202602_COMP.html")))
    assert fields["__VIEWSTATE"] == "LIST-__VIEWSTATE"
    assert fields["__EVENTVALIDATION"] == "LIST-__EVENTVALIDATION"


def test_parse_list_rows() -> None:
    rows = {r.code_raw: r for r in parse_list(soup(fixture_html("list_202602_COMP.html")))}

    lecture = rows["COMP 131 1"]
    assert (lecture.dept, lecture.number, lecture.section, lecture.lab_section) == (
        "COMP",
        "131",
        "1",
        None,
    )
    assert lecture.title == "Fundamentals of Computer Science"
    assert lecture.units == "4"
    assert [i.full for i in lecture.instructors] == [
        "Hector Miguel Camarillo Abad",
        "Meiqing Zhang",
    ]
    assert lecture.instructors[0].short == "Camarillo Abad,H"
    assert lecture.core[0].value == "CPLS"
    assert lecture.meetings == [["10:40am-11:35am", "MWF"]]
    assert lecture.event_target.startswith("gvResults$ctl")
    assert not lecture.is_dash_lab

    lab = rows["COMP 131 1-1"]
    assert lab.lab_section == "1"
    assert lab.is_dash_lab
    assert lab.title == "Fundamentals of Computer Science Laboratory"

    topics = {code: r.title for code, r in rows.items() if r.number == "395"}
    assert topics == {
        "COMP 395 1": "Special Topics in Computer Science. "
        "Artificial Intelligence and Learning Technologies",
        "COMP 395 2": "Special Topics in Computer Science. Deep Learning",
    }


def test_page_without_grid_has_no_rows() -> None:
    assert parse_list(soup(fixture_html("home.html"))) == []


def test_detail_crn() -> None:
    assert detail_crn(soup(fixture_html("detail_202602_2963.html"))) == "2963"
    assert detail_crn(soup(fixture_html("list_202602_COMP.html"))) is None


def test_detail_description() -> None:
    text = detail_description(soup(fixture_html("detail_202602_2963.html")))
    assert text is not None and text.startswith("This course will begin with an exploration")
    assert detail_description(soup(fixture_html("home.html"))) is None


def test_parse_detail_with_prerequisites() -> None:
    detail = parse_detail(soup(fixture_html("detail_202602_2963.html")))
    assert detail is not None
    assert detail.crn == "2963"
    assert detail.description is not None and detail.description.startswith("This course will")
    assert detail.restrictions[-1] == "Course may be repeated for credit."
    assert detail.prerequisites[0] == Prerequisite("( COMP 131", "D", "", "U")
    assert detail.prerequisites[-1] == Prerequisite("or APCS)", "4", "", "")
    assert len(detail.prerequisites) == 10
    assert detail.corequisites is None
    assert detail.reserved_seats == []


def test_parse_detail_with_corequisites_and_reserved_seats() -> None:
    detail = parse_detail(soup(fixture_html("detail_202702_2134.html")))
    assert detail is not None
    assert detail.crn == "2134"
    assert detail.corequisites == "KINE 300L"
    assert detail.reserved_seats == [
        ReservedSeats("Major", 14, 14),
        ReservedSeats("Transfer", 4, 4),
    ]
    assert detail.prerequisites == []
    assert parse_detail(soup(fixture_html("list_202602_COMP.html"))) is None
