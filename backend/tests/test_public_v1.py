import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app
from app.services.catalog_export import term_catalog

from .factories import Factory

PLANNER = "https://planner.example.org"
PUBLISHED = "2026-11-10T08:00:00Z"


@pytest.fixture
def catalog(db: Session) -> None:
    f = Factory(db)
    walsh = f.professor("walsh-joel")
    comp = f.course(
        "COMP-131",
        "Fundamentals of Computer Science",
        numbers=[{"number": "131", "terms": ["202601", "202602"]}],
        related=[{"key": "COMP-101", "relation": "see_also"}],
    )
    f.course("COMP-101", "Intro")
    lecture = f.section(comp, "202601", "1001", "COMP 131 1", [walsh])
    lab = f.section(comp, "202601", "1002", "COMP 131 1-1", [walsh])
    lab.parent = lecture
    f.section(comp, "202602", "2001", "COMP 131 1", [walsh])
    for n in range(30):  # enough sections for a response worth compressing
        f.section(comp, "202602", str(2100 + n), f"COMP 131 {n + 2}")
    db.flush()


ClientFor = Callable[..., TestClient]


@pytest.fixture
def client_for(db: Session, tmp_path: Path) -> Iterator[ClientFor]:
    """Clients on the rolled-back session, with their own settings. The export folder is a temp
    folder holding a catalog-index.json published at PUBLISHED unless `published=False`."""
    clients: list[TestClient] = []

    def make(published: bool = True, **settings: str) -> TestClient:
        folder = tmp_path / f"export{len(clients)}"
        folder.mkdir()
        if published:
            index = {"schema_version": 1, "generated_at": PUBLISHED}
            (folder / "catalog-index.json").write_text(json.dumps(index))
        app = create_app(Settings(catalog_export_dir=folder, **settings))  # type: ignore[arg-type]
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


@pytest.fixture
def api(client_for: ClientFor) -> TestClient:
    return client_for()


@pytest.fixture
def cors_api(client_for: ClientFor) -> TestClient:
    return client_for(cors_origins=f"{PLANNER}, http://localhost:5280")


def test_catalog_is_the_export_file(api: TestClient, db: Session, catalog: None) -> None:
    resp = api.get("/api/v1/catalog?term=202601")
    assert resp.status_code == 200
    body = resp.json()
    published = datetime(2026, 11, 10, 8, tzinfo=UTC)
    assert body == term_catalog(db, "202601", published).model_dump(mode="json")
    assert body["generated_at"] == PUBLISHED  # when the data was published, as in the files
    assert body["schema_version"] == 1
    assert [(s["crn"], s["parent_crn"]) for s in body["sections"]] == [
        ("1001", None),
        ("1002", "1001"),
    ]


def test_index_lists(api: TestClient, catalog: None) -> None:
    assert [t["code"] for t in api.get("/api/v1/terms").json()] == ["202601", "202602"]
    assert api.get("/api/v1/terms").json()[0]["academic_year"] == "2025-26"
    assert api.get("/api/v1/departments").json() == [{"code": "COMP", "name": "COMP Department"}]
    assert api.get("/api/v1/core-areas").json() == []


def test_course_and_professor(api: TestClient, catalog: None) -> None:
    course = api.get("/api/v1/courses/COMP-131").json()
    assert course["key"] == "COMP-131" and course["dept"] == "COMP"
    assert course["related"] == [{"key": "COMP-101", "relation": "see_also"}]
    professor = api.get("/api/v1/professors/walsh-joel").json()
    assert professor == {
        "key": "walsh-joel",
        "display_name": "Joel Walsh",
        "first_name": "Joel",
        "last_name": "Walsh",
        "departments": ["COMP"],
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/catalog?term=209901",
        "/api/v1/courses/NOPE-1",
        "/api/v1/professors/nobody-here",
    ],
)
def test_unknown_keys_are_404(api: TestClient, catalog: None, path: str) -> None:
    resp = api.get(path)
    assert resp.status_code == 404 and resp.json()["detail"].startswith("No ")


def test_catalog_needs_a_term(api: TestClient, catalog: None) -> None:
    assert api.get("/api/v1/catalog").status_code == 422


def test_unchanged_data_is_not_sent_again(api: TestClient, catalog: None) -> None:
    first = api.get("/api/v1/catalog?term=202602")
    assert first.headers["cache-control"] == "public, max-age=300"
    etag = first.headers["etag"]
    assert api.get("/api/v1/catalog?term=202602").content == first.content  # same every time
    again = api.get("/api/v1/catalog?term=202602", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    other = api.get("/api/v1/catalog?term=202601", headers={"If-None-Match": etag})
    assert other.status_code == 200


def test_catalog_is_gzipped(api: TestClient, catalog: None) -> None:
    resp = api.get("/api/v1/catalog?term=202602", headers={"Accept-Encoding": "gzip"})
    assert resp.headers["content-encoding"] == "gzip"


def test_cors_allows_only_listed_sites_on_v1(cors_api: TestClient, catalog: None) -> None:
    allowed = cors_api.get("/api/v1/terms", headers={"Origin": PLANNER})
    assert allowed.headers["access-control-allow-origin"] == PLANNER
    other = cors_api.get("/api/v1/terms", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    # The site's own API is not opened to other sites.
    internal = cors_api.get("/api/departments", headers={"Origin": PLANNER})
    assert "access-control-allow-origin" not in internal.headers

    preflight = cors_api.options(
        "/api/v1/terms",
        headers={"Origin": PLANNER, "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    refused = cors_api.options(
        "/api/v1/terms",
        headers={"Origin": PLANNER, "Access-Control-Request-Method": "POST"},
    )
    assert refused.status_code == 400


def test_no_cors_by_default(api: TestClient, catalog: None) -> None:
    resp = api.get("/api/v1/terms", headers={"Origin": PLANNER})
    assert "access-control-allow-origin" not in resp.headers


def test_without_an_export_generated_at_is_now(client_for: ClientFor, catalog: None) -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    body = client_for(published=False).get("/api/v1/catalog?term=202601").json()
    assert datetime.fromisoformat(body["generated_at"]) >= before
