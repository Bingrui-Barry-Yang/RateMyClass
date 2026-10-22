import pytest

from oxy_scraper.names import maybe_same_person, parse_name
from oxy_scraper.titles import (
    fix_question_marks,
    has_topic_prefix,
    slugify,
    split_title,
    strip_lab_suffix,
    title_key,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Special Topics in Computer Science. Deep Learning",
            ("Special Topics in Computer Science", "Deep Learning"),
        ),
        (
            "Special Topics in Computer Science: Deep Learning",
            ("Special Topics in Computer Science", "Deep Learning"),
        ),
        (
            "Topics in Art History- Encoding Equity: Art and AI",
            ("Topics in Art History", "Encoding Equity: Art and AI"),
        ),
        (
            "History Colloquium:Christianity and Politics",
            ("History Colloquium", "Christianity and Politics"),
        ),
        ("Topics in History: U.S. Presidents", ("Topics in History", "U.S. Presidents")),
        ("Mexico-U.S. Borderlands", ("Mexico-U.S. Borderlands", None)),
        ("St. Louis Blues", ("St. Louis Blues", None)),
        ("Calculus 1-A Laboratory", ("Calculus 1-A Laboratory", None)),
        ("Special Topics in Computer Science", ("Special Topics in Computer Science", None)),
    ],
)
def test_split_title(title: str, expected: tuple[str, str | None]) -> None:
    assert split_title(title) == expected


def test_topic_prefix() -> None:
    assert has_topic_prefix("Special Topics in Biology")
    assert has_topic_prefix("Topic: Whiteness")
    assert has_topic_prefix("Special Topic in Biology: Sleep")
    assert not has_topic_prefix("Junior Seminar: Advanced Topics in Global Sustainability")


def test_slug_and_title_key() -> None:
    assert slugify("Science, Technology, & Justice") == "science-technology-and-justice"
    assert slugify("Since the Nineteenth Century") == slugify("since the nineteenth century")
    assert title_key("Fundamentals/Computer Sci Lab") == title_key(
        "Fundamentals of Computer Science Laboratory"
    )
    assert title_key("Digital Photography") != title_key("Photography Fundamentals")
    assert strip_lab_suffix("The Biology of COVID-19 Laboratory") == "The Biology of COVID-19"


def test_fix_question_marks_keeps_real_questions() -> None:
    assert fix_question_marks("The White Man?s Burden") == "The White Man's Burden"
    assert fix_question_marks("the role ? if any ? of") == "the role \u2014 if any \u2014 of"
    assert fix_question_marks("What Was the Enlightenment?") == "What Was the Enlightenment?"
    assert fix_question_marks("Why This and What Else?: Criticism") == (
        "Why This and What Else?: Criticism"
    )


def test_parse_name_uses_short_form_for_surname() -> None:
    name = parse_name("Hector Miguel Camarillo Abad", "Camarillo Abad,H")
    assert (name.first, name.last, name.key) == (
        "Hector Miguel",
        "Camarillo Abad",
        "camarillo-abad-hector-miguel",
    )
    assert parse_name("Thomas Y. Yeh", "Yeh,T").key == "yeh-thomas-y"


def test_maybe_same_person() -> None:
    yeh = parse_name("Thomas Yeh", "Yeh,T")
    assert maybe_same_person(yeh, parse_name("Thomas Y. Yeh", "Yeh,T"))
    assert maybe_same_person(yeh, parse_name("T. Yeh", "Yeh,T"))
    assert not maybe_same_person(
        parse_name("Matthew Hill", "Hill,M"), parse_name("Michael G. Hill", "Hill,M")
    )
