def test_get_courses_returns_empty_paginated_shape(client):
    response = client.get("/api/v1/courses")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_get_courses_returns_paginated_cards(client, seeded_course):
    response = client.get("/api/v1/courses")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["course_code"] == "PSYCH 210"
    assert body["items"][0]["rating"] == 9.2
    assert body["items"][0]["difficulty"] == 6.0
    assert body["items"][0]["reviews_count"] == 2
    assert body["items"][0]["instructor"]["full_name"] == "Dr. Emily Thompson"


def test_get_course_returns_aggregated_detail(client, seeded_course):
    response = client.get(f"/api/v1/courses/{seeded_course['course_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Introduction to cognitive processes."
    assert body["rating"] == 9.2
    assert body["difficulty"] == 6.0
    assert body["reviews_count"] == 2


def test_create_course_succeeds_for_valid_instructor(client, db_session):
    from app import crud

    instructor = crud.seed_instructor(db_session, full_name="Dr. Sarah Lee", department="MATH")
    response = client.post(
        "/api/v1/courses",
        json={
            "course_code": "MATH 101",
            "course_name": "Calculus I",
            "department": "MATH",
            "description": "Limits and derivatives.",
            "instructor_id": instructor.id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["course_code"] == "MATH 101"
    assert body["instructor"]["full_name"] == "Dr. Sarah Lee"
    assert body["rating"] is None
    assert body["difficulty"] is None
    assert body["reviews_count"] == 0


def test_create_course_returns_404_for_missing_instructor(client):
    response = client.post(
        "/api/v1/courses",
        json={
            "course_code": "HIST 100",
            "course_name": "World History",
            "department": "HIST",
            "description": "History overview.",
            "instructor_id": 999,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Instructor not found"}


def test_course_list_supports_search_sort_and_pagination(client, seeded_course):
    response = client.get(
        "/api/v1/courses",
        params={"search": "Cognitive", "sort_by": "rating", "sort_order": "desc", "page": 1, "page_size": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
