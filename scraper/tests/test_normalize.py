from pathlib import Path

import pytest

from oxy_scraper.normalize import term_info, write_result
from oxy_scraper.overrides import CourseOverride, Overrides, load_overrides

from .builders import WALSH, Term, courses, run, sections


def test_term_info() -> None:
    assert term_info("202601") == {
        "code": "202601",
        "label": "2025 Fall",
        "year": 2025,
        "season": "fall",
        "academic_year": "2025-26",
    }
    assert term_info("202603")["label"] == "2026 Summer"


def test_special_topics_split_by_subtitle_and_merge_across_spellings() -> None:
    spring = (
        Term("202602")
        .add("1", "COMP 395 1", "Special Topics in Computer Science. AI and Learning")
        .add("2", "COMP 395 2", "Special Topics in Computer Science. Deep Learning")
    )
    fall = Term("202701").add(
        "3", "COMP 395 1", "Special Topics in Computer Science: Deep Learning"
    )
    old = Term("202102").add(
        "4", "COMP 395 0", "Special Topics in Computer Science", profs=(("Thomas Yeh", "Yeh,T"),)
    )
    result = run(spring, fall, old)
    c = courses(result)

    assert set(c) == {
        "COMP-395-ai-and-learning",
        "COMP-395-deep-learning",
        "COMP-395-untitled-yeh-thomas",
    }
    assert c["COMP-395-deep-learning"]["title"] == "Deep Learning"
    assert c["COMP-395-deep-learning"]["is_topic"] is True
    assert c["COMP-395-deep-learning"]["title_variants"] == [
        "Special Topics in Computer Science. Deep Learning",
        "Special Topics in Computer Science: Deep Learning",
    ]
    assert c["COMP-395-untitled-yeh-thomas"]["title"] == "Special Topics in Computer Science (Yeh)"
    topic_rows = result.reports["topic_courses"][1]
    assert {r[2] for r in topic_rows} == {"topics title"}


def test_plain_topics_title_without_subtitles_is_a_normal_course() -> None:
    t = Term("202601").add("1", "BLST 105 0", "Topics in American Music")
    t2 = Term("202701").add("2", "BLST 105 0", "Topics in American Music")
    assert set(courses(run(t, t2))) == {"BLST-105"}


def test_shared_main_title_with_different_subtitles_is_a_topics_number() -> None:
    t = (
        Term("202601")
        .add("1", "ECON 495 1", "Senior Seminar: Health Economics")
        .add("2", "ECON 495 2", "Senior Seminar: Industrial Organization")
    )
    c = courses(run(t))
    assert c["ECON-495-health-economics"]["title"] == "Senior Seminar: Health Economics"
    assert "ECON-495-industrial-organization" in c


def test_topics_vary_description_makes_each_title_a_course() -> None:
    t = (
        Term("202601")
        .add("1", "ENGL 365 1", "Contemporary Literature", description="Topics vary.")
        .add("2", "ENGL 365 2", "Poetry Now", description="Topics vary.")
    )
    assert set(courses(run(t))) == {
        "ENGL-365-contemporary-literature",
        "ENGL-365-poetry-now",
    }


def test_lecture_title_wins_and_lab_spellings_do_not_split() -> None:
    a = (
        Term("202202")
        .add("10", "COMP 131 1", "Fundamentals of Computer Science")
        .add(
            "11", "COMP 131 1-1", "Fundamentals/Computer Sci Lab", profs=(("Ann David", "David,A"),)
        )
    )
    b = (
        Term("202602")
        .add("20", "COMP 131 2", "Fundamentals of Computer Science")
        .add("21", "COMP 131 2-1", "Fundamentals of Computer Science Laboratory")
    )
    result = run(a, b)
    c = courses(result)
    s = sections(result)

    assert set(c) == {"COMP-131"}
    assert c["COMP-131"]["title"] == "Fundamentals of Computer Science"
    lab = s[("202202", "COMP 131 1-1")]
    assert (lab["kind"], lab["parent_crn"], lab["course_key"]) == ("lab", "10", "COMP-131")
    assert lab["professor_keys"] == ["david-ann"]
    assert result.reports["title_changes"][1] == []


def test_lab_numbers_join_the_base_course_or_the_matching_topic() -> None:
    t = (
        Term("202102")
        .add("1", "BIO 224 0", "Animal Physiology")
        .add("2", "BIO 224L 1", "Animal Physiology Laboratory", profs=(("Ann Lab", "Lab,A"),))
        .add("3", "BIO 393 1", "Special Topics in Biology: Biology of COVID-19")
        .add("4", "BIO 393 2", "Special Topics in Biology: Sleep")
        .add("5", "BIO 393L 1", "Special Topics in Biology: Biology of COVID-19 Laboratory")
    )
    s = sections(run(t))
    assert (s[("202102", "BIO 224L 1")]["course_key"], s[("202102", "BIO 224L 1")]["kind"]) == (
        "BIO-224",
        "lab",
    )
    assert s[("202102", "BIO 393L 1")]["course_key"] == "BIO-393-biology-of-covid-19"


def test_cross_lists_need_same_time_and_two_departments() -> None:
    t = (
        Term("202601")
        .add("1", "AMST 329 1", "Race and Memory")
        .add("2", "BLST 329 1", "Race and Memory")
        .add("3", "ARTS 203 0", "Intermediate Sculpture", meetings=[("01:00pm-03:00pm", "TR")])
        .add("4", "ARTS 303 0", "Advanced Sculpture", meetings=[("01:00pm-03:00pm", "TR")])
        .add("5", "CHEM 295 1", "Directed Research", meetings=[("Time-TBD", "Days-TBD")])
        .add("6", "KINE 395 1", "Directed Research", meetings=[("Time-TBD", "Days-TBD")])
    )
    s = sections(run(t))
    assert s[("202601", "AMST 329 1")]["cross_list_group"] == "202601:AMST 329 1+BLST 329 1"
    assert s[("202601", "BLST 329 1")]["cross_list_group"] == "202601:AMST 329 1+BLST 329 1"
    for code in ("ARTS 203 0", "ARTS 303 0", "CHEM 295 1", "KINE 395 1"):
        assert s[("202601", code)]["cross_list_group"] is None


def test_exclusions_are_dropped_and_reported() -> None:
    t = (
        Term("202102")
        .add("1", "COMP 131 1", "Fundamentals of Computer Science")
        .add("9", "COMP 131 9", "Fund/Comp Sci (Credit by Exam)")
    )
    result = run(t)
    assert [s["crn"] for s in result.sections] == ["1"]
    assert result.reports["excluded"][1] == [
        ["202102", "9", "COMP 131 9", "Fund/Comp Sci (Credit by Exam)", "credit by exam"]
    ]


def test_description_history_and_question_mark_repair() -> None:
    old = Term("202201").add("1", "DWA 280 0", "Globalization", description="Old text.")
    new = Term("202301").add(
        "2",
        "DWA 280 0",
        "Globalization",
        description="The world?s new text.",
        restrictions=("Course may be repeated for credit.",),
    )
    newest = Term("202401").add(
        "3", "DWA 280 0", "Globalization", description="The world?s new text."
    )
    result = run(old, new, newest)
    course = courses(result)["DWA-280"]

    assert course["description"] == "The world's new text."
    assert course["description_history"] == [
        {"from_term": "202301", "to_term": "202401", "text": "The world's new text."},
        {"from_term": "202201", "to_term": "202201", "text": "Old text."},
    ]
    assert course["repeatable"] is False  # latest term's restrictions only
    change = result.reports["description_changes"][1][0]
    assert change[:3] == ["DWA-280", "202201", "202301"]


def test_real_renames_are_reported() -> None:
    a = Term("202402").add("1", "ARTS 107 0", "Digital Photography")
    b = Term("202501").add("2", "ARTS 107 0", "Photography Fundamentals")
    result = run(a, b)
    assert courses(result)["ARTS-107"]["title"] == "Photography Fundamentals"
    assert {r[1] for r in result.reports["title_changes"][1]} == {
        "Digital Photography",
        "Photography Fundamentals",
    }


def test_overrides() -> None:
    t = (
        Term("202102")
        .add("1", "COMP 395 0", "Special Topics in Computer Science")
        .add("2", "COMP 395 1", "Special Topics in Computer Science: Data Mining")
        .add("3", "COMP 395 2", "Special Topics in Computer Science: Data-Mining Methods")
        .add("4", "FYS 11 0", "Histories of Incarcerated Youth")
        .add("5", "FYS 11 1", "Animal Intelligence", profs=(("Thomas Y. Yeh", "Yeh,T"),))
    )
    overrides = Overrides(
        courses=[
            CourseOverride("set_topic", "202102", "1", "", "Computer Architecture", ""),
            CourseOverride(
                "merge_into", "", "", "COMP-395-data-mining-methods", "COMP-395-data-mining", ""
            ),
            CourseOverride("set_title", "", "", "COMP-395-data-mining", "Data Mining", ""),
            CourseOverride("split_by_title", "", "", "FYS", "", ""),
        ],
        professor_aliases={"Thomas Y. Yeh": "walsh-joel-anderson"},
    )
    result = run(t, overrides=overrides)
    c = courses(result)

    assert set(c) == {
        "COMP-395-computer-architecture",
        "COMP-395-data-mining",
        "FYS-histories-of-incarcerated-youth",
        "FYS-animal-intelligence",
    }
    assert c["COMP-395-data-mining"]["title"] == "Data Mining"
    s = sections(result)
    assert s[("202102", "COMP 395 2")]["course_key"] == "COMP-395-data-mining"
    assert s[("202102", "FYS 11 1")]["professor_keys"] == ["walsh-joel-anderson"]
    assert [p["key"] for p in result.professors] == ["walsh-joel-anderson"]


def test_unknown_merge_key_is_an_error() -> None:
    t = Term("202102").add("1", "COMP 131 1", "Fundamentals of Computer Science")
    bad = Overrides(courses=[CourseOverride("merge_into", "", "", "COMP-999", "COMP-131", "")])
    with pytest.raises(ValueError, match="COMP-999"):
        run(t, overrides=bad)


def test_professors_and_suspects() -> None:
    a = Term("202201").add("1", "COMP 131 1", "Fundamentals", profs=(("Thomas Yeh", "Yeh,T"),))
    b = Term("202301").add(
        "2", "COMP 131 1", "Fundamentals", profs=(("Thomas Y. Yeh", "Yeh,T"), WALSH)
    )
    result = run(a, b)
    keys = {p["key"]: p for p in result.professors}
    assert set(keys) == {"yeh-thomas", "yeh-thomas-y", "walsh-joel-anderson"}
    assert keys["walsh-joel-anderson"]["departments"] == ["COMP"]
    assert sections(result)[("202301", "COMP 131 1")]["professor_keys"] == [
        "yeh-thomas-y",
        "walsh-joel-anderson",
    ]
    suspects = result.reports["professor_suspects"][1]
    assert [(r[0], r[3]) for r in suspects] == [("yeh-thomas", "yeh-thomas-y")]


def test_write_result_and_committed_overrides_load(tmp_path: Path) -> None:
    result = run(Term("202601").add("1", "COMP 131 1", "Fundamentals"))
    write_result(result, tmp_path / "normalized", tmp_path / "reports")
    assert (tmp_path / "normalized" / "courses.json").exists()
    assert (tmp_path / "reports" / "topic_courses.csv").read_text().startswith("course_key,")
    table = (tmp_path / "reports" / "all_sections.csv").read_text().splitlines()
    assert table[0].startswith("term,term_label,dept,code,kind,crn,course_title")
    assert table[1].startswith("202601,2025 Fall,COMP,COMP 131 1,lecture,1,Fundamentals")
    by_course = (tmp_path / "reports" / "all_courses.csv").read_text().splitlines()
    assert by_course[0].startswith("course_key,dept,number,title,topic,numbers_and_terms")
    assert by_course[1].startswith("COMP-131,COMP,131,Fundamentals,,COMP 131 (2025 Fall),2025 Fall")
    assert "FYS" in load_overrides().split_by_title()  # scraper/overrides/ parses


def test_malformed_override_rows_are_errors(tmp_path: Path) -> None:
    (tmp_path / "professor_aliases.csv").write_text("alias_full_name,canonical_key,note\n")
    (tmp_path / "course_overrides.csv").write_text(
        "action,term,crn,course_key,value,note\nrename,,,COMP-131,X,\n"
    )
    with pytest.raises(ValueError, match="unknown action 'rename'"):
        load_overrides(tmp_path)
    (tmp_path / "course_overrides.csv").write_text(
        "action,term,crn,course_key,value,note\nset_topic,202102,,,Data,\n"
    )
    with pytest.raises(ValueError, match="set_topic needs term, crn and value"):
        load_overrides(tmp_path)


def test_untitled_sections_group_by_number_and_professors() -> None:
    a = Term("202102").add("1", "BIO 103 0", "Topics in Biology: Urban Ecology")
    a.add("2", "BIO 103 1", "Topics in Biology", profs=(("Jon Williams", "Williams,J"),))
    b = Term("202202").add(
        "3", "BIO 103 0", "Topics in Biology", profs=(("Jon Williams", "Williams,J"),)
    )
    b.add("4", "BIO 103 1", "Topics in Biology", profs=())
    c = courses(run(a, b))
    assert c["BIO-103-untitled-williams-jon"]["title"] == "Topics in Biology (Williams)"
    assert c["BIO-103-untitled-williams-jon"]["numbers"] == [
        {"number": "103", "terms": ["202102", "202202"]}
    ]
    assert c["BIO-103-untitled-202202-4"]["title"] == "Topics in Biology (Spring 2022)"


def test_topics_will_vary_needs_more_than_one_title() -> None:
    t = Term("202601").add(
        "1", "LLAS 101 0", "Intro to Latin American Studies", description="Topics will vary."
    )
    t2 = Term("202701").add(
        "2", "LLAS 101 0", "Intro to Latin American Studies", description="Topics will vary."
    )
    assert set(courses(run(t, t2))) == {"LLAS-101"}
    t3 = Term("202702").add("3", "LLAS 101 0", "Borderlands", description="Topics will vary.")
    assert "LLAS-101-borderlands" in courses(run(t, t2, t3))


def test_placeholder_instructor_is_no_professor() -> None:
    t = Term("202702").add(
        "1", "CHEM 101 0", "Chemistry", profs=(("Instructor Unassigned", "Unassigned,I"), WALSH)
    )
    result = run(t)
    assert [p["key"] for p in result.professors] == ["walsh-joel-anderson"]
    assert result.sections[0]["professor_keys"] == ["walsh-joel-anderson"]


def test_fys_seminar_keeps_one_course_across_numbers() -> None:
    a = Term("202501").add("1", "FYS 24 0", "Imagining Freedom")
    b = Term("202601").add("2", "FYS 13 0", "Imagining Freedom")
    split = Overrides(courses=[CourseOverride("split_by_title", "", "", "FYS", "", "")])
    course = courses(run(a, b, overrides=split))["FYS-imagining-freedom"]
    assert course["number"] == "13"
    assert course["numbers"] == [
        {"number": "24", "terms": ["202501"]},
        {"number": "13", "terms": ["202601"]},
    ]


LONG = "This course studies black holes, curved space-time and gravitational waves in depth. " * 3


def test_renumbered_course_merges_into_the_newer_number() -> None:
    old = Term("202102").add("1", "PHYS 266 0", "Space, Time, and Black Holes", description=LONG)
    new = Term("202701").add("2", "PHYS 206 0", "Space, Time, and Black Holes", description=LONG)
    result = run(old, new)
    c = courses(result)
    assert set(c) == {"PHYS-206"}
    assert c["PHYS-206"]["numbers"] == [
        {"number": "266", "terms": ["202102"]},
        {"number": "206", "terms": ["202701"]},
    ]
    assert result.reports["renumbered"][1][0][:3] == ["PHYS-266", "202102", "PHYS-206"]


def test_renumbering_is_not_merged_across_levels_series_or_keep_apart() -> None:
    level = (
        Term("202102").add("1", "AMST 233 0", "American Queer Novel", description=LONG),
        Term("202401").add("2", "AMST 333 0", "American Queer Novel", description=LONG),
    )
    series = (
        Term("202201").add("3", "FREN 151 0", "Intermediate Conversation I", description=LONG),
        Term("202202").add("4", "FREN 152 0", "Intermediate Conversation II", description=LONG),
    )
    sister = (
        Term("202602").add("5", "SOC 225 0", "Masculinities", description=LONG),
        Term("202702").add("6", "SOC 226 0", "Masculinities in Latin America", description=LONG),
    )
    apart = Overrides(courses=[CourseOverride("keep_apart", "", "", "SOC-225", "SOC-226", "")])
    result = run(*level, *series, *sister, overrides=apart)
    assert set(courses(result)) == {
        "AMST-233",
        "AMST-333",
        "FREN-151",
        "FREN-152",
        "SOC-225",
        "SOC-226",
    }
    reasons = {r[0]: r[7] for r in result.reports["renumbered"][1]}
    assert reasons == {"AMST-233": "different course levels: kept apart"}


def test_topic_report_points_at_same_description() -> None:
    t = (
        Term("202102")
        .add(
            "1",
            "CTSJ 295 1",
            "Topics in CTSJ: Critical Theory and Psychopathology",
            description=LONG,
        )
        .add(
            "2",
            "CTSJ 295 2",
            "Topics in CTSJ - Social Justice: Psychopathology Now",
            description=LONG,
            profs=(("Ann Lee", "Lee,A"),),
        )
    )
    rows = {r[0]: r for r in run(t).reports["topic_courses"][1]}
    assert rows["CTSJ-295-critical-theory-and-psychopathology"][4] == (
        "CTSJ-295-social-justice-psychopathology-now"
    )


def test_same_description_and_professor_make_one_course_whatever_the_title() -> None:
    old = Term("202201").add("1", "WRD 201 1", "Essay Writing: White Privilege", description=LONG)
    old.add(
        "2", "WRD 201 2", "Essay Writing: Art House Cinema", profs=(("Ara Corbett", "Corbett,A"),)
    )
    new = Term("202401").add(
        "3", "WRD 201 1", "Essay Writing: Class and Whiteness", description=LONG
    )
    result = run(old, new)
    assert set(courses(result)) == {
        "WRD-201-class-and-whiteness",
        "WRD-201-art-house-cinema",
    }
    assert result.reports["evidence_merges"][1] == [
        ["WRD-201-white-privilege", "WRD-201-class-and-whiteness", 1.0, "walsh-joel-anderson"]
    ]
    other = Term("202401").add(
        "3",
        "WRD 201 1",
        "Essay Writing: Class and Whiteness",
        description=LONG,
        profs=(("Ann Lee", "Lee,A"),),
    )
    assert len(courses(run(old, other))) == 3  # no shared professor: kept apart
    apart = Overrides(
        courses=[
            CourseOverride(
                "keep_apart", "", "", "WRD-201-white-privilege", "WRD-201-class-and-whiteness", ""
            )
        ]
    )
    assert len(courses(run(old, new, overrides=apart))) == 3


def test_topic_spellings_that_differ_by_abbreviation_share_a_key() -> None:
    t = (
        Term("202102")
        .add("1", "COMP 395 1", "Special Topics in Computer Science: Intro to Data Sci")
        .add("2", "COMP 395 2", "Special Topics in Computer Science: Other/Realities")
    )
    t2 = (
        Term("202202")
        .add("3", "COMP 395 1", "Special Topics in Computer Science: Introduction to Data Science")
        .add("4", "COMP 395 2", "Special Topics in Computer Science: Other Realities")
    )
    assert set(courses(run(t, t2))) == {"COMP-395-intro-to-data-sci", "COMP-395-other-realities"}
