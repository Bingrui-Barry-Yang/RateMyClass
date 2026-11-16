from app.models import Course
from app.services.catalog_export import description_for


def test_description_for_picks_the_wording_of_the_term() -> None:
    course = Course(
        description="New text.",
        description_history=[
            {"from_term": "202702", "to_term": "202702", "text": "New text."},
            {"from_term": "202101", "to_term": "202502", "text": "Old text."},
        ],
    )
    assert description_for(course, "202302") == "Old text."
    assert description_for(course, "202702") == "New text."
    assert description_for(course, "202601") == "New text."  # not offered then: latest
