def test_post_review_succeeds_for_existing_course(client, seeded_course):
    response = client.post(
        "/api/v1/reviews",
        json={
            "course_id": seeded_course["course_id"],
            "rating": 8.5,
            "difficulty": 5.5,
            "comment": "Very well structured.",
            "reviewer_name": "Anonymous",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["course_id"] == seeded_course["course_id"]
    assert body["rating"] == 8.5
    assert body["difficulty"] == 5.5


def test_post_review_rejects_out_of_range_values(client, seeded_course):
    response = client.post(
        "/api/v1/reviews",
        json={
            "course_id": seeded_course["course_id"],
            "rating": 11,
            "difficulty": 5,
            "comment": "Impossible score.",
        },
    )

    assert response.status_code == 422


def test_get_course_reviews_returns_only_that_courses_reviews(client, seeded_course):
    response = client.get(f"/api/v1/courses/{seeded_course['course_id']}/reviews")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["course_id"] == seeded_course["course_id"] for item in body["items"])


def test_post_review_updates_aggregates(client, seeded_course):
    response = client.post(
        "/api/v1/reviews",
        json={
            "course_id": seeded_course["course_id"],
            "rating": 6.0,
            "difficulty": 9.0,
            "comment": "Harder than expected.",
        },
    )
    assert response.status_code == 201

    course_response = client.get(f"/api/v1/courses/{seeded_course['course_id']}")
    assert course_response.status_code == 200
    body = course_response.json()
    assert body["reviews_count"] == 3
    assert body["rating"] == 8.1
    assert body["difficulty"] == 7.0


def test_cors_is_configured_for_frontend_origin(client):
    response = client.options(
        "/api/v1/courses",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
