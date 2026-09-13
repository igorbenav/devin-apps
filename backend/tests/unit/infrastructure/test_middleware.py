"""Tests for middleware components."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.infrastructure.middleware import ClientCacheMiddleware, SameOriginMiddleware, SecurityHeadersMiddleware


def _create_app_with_middleware(
    cache: bool = False,
    security: bool = False,
    environment: str = "development",
    max_age: int = 60,
    docs_paths: list[str] | None = None,
) -> FastAPI:
    app = FastAPI()

    if cache:
        app.add_middleware(ClientCacheMiddleware, max_age=max_age)
    if security:
        app.add_middleware(SecurityHeadersMiddleware, environment=environment, docs_paths=docs_paths)

    @app.get("/api/v1/users")
    async def api_route():
        return {"users": []}

    @app.get("/static/logo.png")
    async def static_route():
        return {"file": "logo"}

    @app.get("/audit")
    async def page_route():
        return {"events": []}

    return app


# === ClientCacheMiddleware ===


@pytest.mark.asyncio
async def test_api_paths_get_no_cache():
    app = _create_app_with_middleware(cache=True, max_age=120)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/users")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "private, no-cache, no-store, must-revalidate"


@pytest.mark.asyncio
async def test_static_paths_get_public_cache():
    app = _create_app_with_middleware(cache=True, max_age=120)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/static/logo.png")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=120"


@pytest.mark.asyncio
async def test_html_pages_get_no_cache():
    app = _create_app_with_middleware(cache=True, max_age=120)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/audit")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "private, no-cache, no-store, must-revalidate"


# === SecurityHeadersMiddleware ===


@pytest.mark.asyncio
async def test_security_headers_present_in_dev():
    app = _create_app_with_middleware(security=True, environment="development")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/users")

    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["x-xss-protection"] == "0"
    assert "camera=()" in resp.headers["permissions-policy"]
    # HSTS should NOT be set in dev
    assert "strict-transport-security" not in resp.headers


@pytest.mark.asyncio
async def test_hsts_set_in_production():
    app = _create_app_with_middleware(security=True, environment="production")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/users")

    assert "strict-transport-security" in resp.headers
    assert "max-age=" in resp.headers["strict-transport-security"]
    assert "includeSubDomains" in resp.headers["strict-transport-security"]


@pytest.mark.asyncio
async def test_hsts_set_in_staging():
    app = _create_app_with_middleware(security=True, environment="staging")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/users")

    assert "strict-transport-security" in resp.headers


# === Content-Security-Policy ===


@pytest.mark.asyncio
async def test_csp_forbids_inline_script_outside_admin():
    app = _create_app_with_middleware(security=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/audit")

    policy = resp.headers["content-security-policy"]
    assert "script-src 'self';" in policy
    assert "unsafe-inline" not in policy
    assert "frame-ancestors 'none'" in policy


@pytest.mark.asyncio
async def test_csp_relaxes_inline_script_for_sqladmin():
    app = _create_app_with_middleware(security=True)

    @app.get("/admin/role/list")
    async def admin_route():
        return {"rows": []}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/role/list")

    assert "script-src 'self' 'unsafe-inline'" in resp.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_csp_allows_the_swagger_bundle_on_the_docs_path():
    app = _create_app_with_middleware(security=True, docs_paths=["/docs"])

    @app.get("/docs")
    async def docs_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        docs = await client.get("/docs")
        other = await client.get("/audit")

    assert "https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in other.headers["content-security-policy"]


# === SameOriginMiddleware ===


def _same_origin_app(allowed_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SameOriginMiddleware, allowed_origins=allowed_origins or [])

    @app.post("/login")
    async def login():
        return {"ok": True}

    @app.get("/login")
    async def login_page():
        return {"ok": True}

    @app.post("/api/v1/users")
    async def api_route():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_cross_origin_post_is_rejected():
    async with AsyncClient(transport=ASGITransport(app=_same_origin_app()), base_url="http://test") as client:
        resp = await client.post("/login", headers={"Origin": "http://evil.example"})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_same_origin_post_is_allowed():
    async with AsyncClient(transport=ASGITransport(app=_same_origin_app()), base_url="http://test") as client:
        resp = await client.post("/login", headers={"Origin": "http://test"})

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_configured_origin_is_allowed_on_the_api():
    app = _same_origin_app(["https://tools.example.com"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/users", headers={"Origin": "https://tools.example.com"})

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_configured_origin_cannot_post_the_login_form():
    """A CORS origin exists for the API; letting it post the login form would reopen login CSRF."""
    app = _same_origin_app(["https://tools.example.com"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/login", headers={"Origin": "https://tools.example.com"})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_request_without_origin_is_left_alone():
    async with AsyncClient(transport=ASGITransport(app=_same_origin_app()), base_url="http://test") as client:
        resp = await client.post("/login")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cross_origin_get_is_allowed():
    async with AsyncClient(transport=ASGITransport(app=_same_origin_app()), base_url="http://test") as client:
        resp = await client.get("/login", headers={"Origin": "http://evil.example"})

    assert resp.status_code == 200
