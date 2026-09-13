"""The browser-facing platform pages: login, launcher, audit."""

import pytest
from httpx import AsyncClient

from src.modules.platform.routes import safe_next_path

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("/tools/kyc", "/tools/kyc"),
        ("//evil.example.com", "/"),
        ("https://evil.example.com", "/"),
        ("/tools\\kyc", "/"),
        ("/tools\nkyc", "/"),
        (None, "/"),
        ("", "/"),
    ],
)
def test_only_same_origin_paths_survive_the_next_parameter(candidate: str | None, expected: str) -> None:
    assert safe_next_path(candidate) == expected


async def test_launcher_redirects_anonymous_users_to_login(client: AsyncClient) -> None:
    response = await client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/"


async def test_audit_page_redirects_anonymous_users_to_login(client: AsyncClient) -> None:
    response = await client.get("/audit", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/audit"


async def test_login_page_renders_the_form(client: AsyncClient) -> None:
    response = await client.get("/login")

    assert response.status_code == 200
    assert '<form method="post" action="/login"' in response.text


async def test_login_rejects_bad_credentials_without_naming_the_field(client: AsyncClient, test_user: dict) -> None:
    response = await client.post("/login", data={"username": test_user["username"], "password": "wrong-password"})

    assert response.status_code == 401
    assert "Invalid username or password" in response.text


async def test_login_starts_a_session_and_lands_on_the_launcher(client: AsyncClient, test_user: dict) -> None:
    response = await client.post(
        "/login",
        data={"username": test_user["username"], "password": test_user["password"]},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Your tools" in response.text
    assert "No tools are available to you yet." in response.text
