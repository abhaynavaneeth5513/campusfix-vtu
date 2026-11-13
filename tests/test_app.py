"""Tests for complaint submission, validation, and the admin session."""

import re

import pytest

from app import (
    ADMIN_USERNAME,
    CATEGORIES,
    DEV_ADMIN_PASSWORD,
    DEV_SECRET_KEY,
    create_app,
)

ADMIN_PASSWORD = "TestAdmin#2026"


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.db"),
            "SECRET_KEY": "test-secret-key-not-for-production",
            "ADMIN_PASSWORD": ADMIN_PASSWORD,
        }
    )
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/"):
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    assert match, "CSRF token was not rendered"
    return match.group(1)


def submit(client, **overrides):
    payload = {
        "csrf_token": csrf(client),
        "title": "Library Wi-Fi keeps dropping",
        "description": "The access point near the reading room disconnects every few minutes.",
        "category": "Wi-Fi",
    }
    payload.update(overrides)
    return client.post("/complaints", data=payload, follow_redirects=False)


def login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    token = csrf(client, "/admin")
    return client.post(
        "/admin/login",
        data={"csrf_token": token, "username": username, "password": password},
        follow_redirects=True,
    )


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.is_json
    assert response.get_json() == {"status": "healthy"}


def test_home_page_lists_categories_and_empty_dashboard(client):
    response = client.get("/")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Submit a complaint" in page
    assert "Complaint dashboard" in page
    assert "No complaints have been submitted yet." in page
    for category in CATEGORIES:
        assert category in page
    assert 'id="stat-total">0' in page


def test_valid_complaint_is_saved_and_shown(client):
    response = submit(client)
    assert response.status_code == 302
    page = client.get("/").get_data(as_text=True)
    assert "Complaint CF-001 submitted." in page
    assert "Library Wi-Fi keeps dropping" in page
    assert "Pending" in page
    assert 'id="stat-pending">1' in page
    assert 'id="stat-total">1' in page


def test_quoted_title_is_stored_and_table_survives(client):
    title = "Router '; DROP TABLE complaints; --"
    response = submit(
        client,
        title=title,
        description="Room 101 loses the campus network during class.",
    )
    assert response.status_code == 302
    page = client.get("/").get_data(as_text=True)
    assert "DROP TABLE" in page
    second = submit(client, title="Projector remote is missing")
    assert second.status_code == 302
    assert "CF-002" in client.get("/").get_data(as_text=True)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"title": "   ", "description": "The lab projector will not turn on.", "category": "Laboratory"},
            "Title is required.",
        ),
        (
            {"title": "Hi", "description": "The lab projector will not turn on.", "category": "Laboratory"},
            "Title must be at least 3 characters.",
        ),
        (
            {"title": "A" * 121, "description": "The lab projector will not turn on.", "category": "Laboratory"},
            "Title must be 120 characters or fewer.",
        ),
        (
            {"title": "Broken chair", "description": "Too short", "category": "Classroom"},
            "Description must be at least 10 characters.",
        ),
        (
            {"title": "Broken chair", "description": "   ", "category": "Classroom"},
            "Description is required.",
        ),
        (
            {
                "title": "Broken chair",
                "description": "The chair in room 12 has a cracked seat.",
                "category": "Hostel",
            },
            "Select a valid category.",
        ),
    ],
)
def test_invalid_complaints_are_rejected(client, payload, message):
    response = submit(client, **payload)
    page = response.get_data(as_text=True)
    assert response.status_code == 400
    assert message in page
    assert "No complaints have been submitted yet." in page


def test_missing_csrf_does_not_save(client):
    response = client.post(
        "/complaints",
        data={
            "title": "Water leak in the corridor",
            "description": "Water is dripping beside classroom 204.",
            "category": "Infrastructure",
        },
    )
    assert response.status_code == 302
    page = client.get("/").get_data(as_text=True)
    assert "No complaints have been submitted yet." in page
    assert "form expired" in page


def test_dashboard_filter_limits_rows(client):
    submit(client, title="Lab benches are loose", category="Laboratory")
    submit(client, title="Ceiling light is out", category="Infrastructure", description="The light outside classroom 12 has failed.")
    lab_page = client.get("/?category=Laboratory").get_data(as_text=True)
    assert "Lab benches are loose" in lab_page
    assert "Ceiling light is out" not in lab_page
    all_page = client.get("/?category=NotACategory").get_data(as_text=True)
    assert "Lab benches are loose" in all_page
    assert "Ceiling light is out" in all_page


def test_admin_page_requires_sign_in(client):
    page = client.get("/admin").get_data(as_text=True)
    assert "Admin sign in" in page
    assert "Save status" not in page
    assert DEV_ADMIN_PASSWORD not in page
    assert DEV_SECRET_KEY not in page


def test_admin_login_rejects_bad_password(client):
    response = login(client, password="wrong-password")
    page = response.get_data(as_text=True)
    assert response.status_code == 401
    assert "Invalid username or password." in page
    assert "Admin dashboard" not in page


def test_status_update_requires_admin_and_then_persists(client):
    submit(client, title="Loose tiles near the lab")
    blocked = client.post(
        "/admin/complaints/1/status",
        data={"csrf_token": csrf(client, "/admin"), "status": "Resolved"},
        follow_redirects=True,
    )
    assert "Sign in as admin to update complaints." in blocked.get_data(as_text=True)
    assert 'id="stat-pending">1' in client.get("/").get_data(as_text=True)
    assert 'id="stat-resolved">0' in client.get("/").get_data(as_text=True)

    signed_in = login(client)
    assert signed_in.status_code == 200
    assert "Admin dashboard" in signed_in.get_data(as_text=True)

    token = csrf(client, "/admin")
    updated = client.post(
        "/admin/complaints/1/status",
        data={"csrf_token": token, "status": "In Progress"},
        follow_redirects=True,
    )
    assert "Complaint CF-001 marked In Progress." in updated.get_data(as_text=True)
    home = client.get("/")
    assert 'id="stat-progress">1' in home.get_data(as_text=True)

    bad_status = client.post(
        "/admin/complaints/1/status",
        data={"csrf_token": csrf(client, "/admin"), "status": "Closed"},
        follow_redirects=True,
    )
    assert "Choose a valid status" in bad_status.get_data(as_text=True)
    assert 'id="stat-progress">1' in client.get("/").get_data(as_text=True)

    missing = client.post(
        "/admin/complaints/999/status",
        data={"csrf_token": csrf(client, "/admin"), "status": "Resolved"},
        follow_redirects=True,
    )
    assert "could not be found" in missing.get_data(as_text=True)


def test_logout_blocks_further_updates(client):
    submit(client)
    login(client)
    client.post(
        "/admin/logout",
        data={"csrf_token": csrf(client, "/admin")},
        follow_redirects=True,
    )
    response = client.post(
        "/admin/complaints/1/status",
        data={"csrf_token": csrf(client, "/admin"), "status": "Resolved"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")
    assert 'id="stat-pending">1' in client.get("/").get_data(as_text=True)


def test_development_defaults_are_warned_and_not_printed(tmp_path, monkeypatch):
    monkeypatch.delenv("CAMPUSFIX_SECRET_KEY", raising=False)
    monkeypatch.delenv("CAMPUSFIX_ADMIN_PASSWORD", raising=False)
    application = create_app({"TESTING": True, "DATABASE": str(tmp_path / "dev.db")})
    page = application.test_client().get("/").get_data(as_text=True)
    assert "Local development defaults are active" in page
    assert DEV_ADMIN_PASSWORD not in page
    assert DEV_SECRET_KEY not in page


def test_environment_password_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPUSFIX_SECRET_KEY", "environment-secret-key")
    monkeypatch.setenv("CAMPUSFIX_ADMIN_PASSWORD", "FromEnv#99")
    application = create_app({"TESTING": True, "DATABASE": str(tmp_path / "env.db")})
    client = application.test_client()
    home = client.get("/").get_data(as_text=True)
    assert "Local development defaults are active" not in home
    response = login(client, password="FromEnv#99")
    assert "Admin dashboard" in response.get_data(as_text=True)
