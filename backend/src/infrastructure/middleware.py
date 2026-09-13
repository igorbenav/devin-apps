"""Middleware components for the FastAPI application."""

from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

# Two years, matching the HSTS preload-list requirement.
HSTS_MAX_AGE_SECONDS = 63072000

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class SameOriginMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests that a browser labels as coming from another site.

    crudauth's synchronizer token covers every request made with an existing session, but the routes that *create* one
    (the browser login form, the SQLAdmin login form) have no session to bind a token to and are plain form posts, which
    ``SameSite`` alone does not stop. Browsers attach ``Origin`` to those posts, so comparing it to this deployment's own
    origin closes login CSRF without touching the session flow. Requests with no ``Origin`` (server-to-server callers,
    curl) are left to the route's own authentication.

    ``CORS_ORIGINS`` is honoured for the JSON API only. Those origins exist so browser clients can call ``/api/v1``;
    letting them post the login forms too would hand every configured origin the login CSRF this middleware exists to
    stop, so the server-rendered pages and ``/admin`` require a strict same-origin post.
    """

    CROSS_ORIGIN_PREFIXES = ("/api/",)

    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None = None) -> None:
        super().__init__(app)
        self.allowed_origins = {origin.rstrip("/") for origin in (allowed_origins or []) if origin != "*"}

    def _is_allowed(self, request: Request, origin: str) -> bool:
        if request.url.path.startswith(self.CROSS_ORIGIN_PREFIXES) and origin.rstrip("/") in self.allowed_origins:
            return True

        parts = urlsplit(origin)
        host = request.headers.get("host")
        return bool(host) and parts.netloc == host

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        if origin and request.method not in SAFE_METHODS and not self._is_allowed(request, origin):
            return JSONResponse(status_code=403, content={"detail": "Cross-origin request rejected"})

        return await call_next(request)


class ClientCacheMiddleware(BaseHTTPMiddleware):
    """Set Cache-Control headers.

    Static assets get public caching with the configured max_age. Everything else is treated as authenticated, dynamic
    content and gets no-store.
    """

    PUBLIC_PREFIXES = ("/static/",)

    def __init__(self, app: ASGIApp, max_age: int = 60) -> None:
        super().__init__(app)
        self.max_age: int = max_age

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        if request.url.path.startswith(self.PUBLIC_PREFIXES):
            response.headers["Cache-Control"] = f"public, max-age={self.max_age}"
        else:
            response.headers["Cache-Control"] = "private, no-cache, no-store, must-revalidate"
        return response


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)

# SQLAdmin's own templates carry inline <script> and style attributes, so the strict policy would break /admin. Its
# assets are still served from this origin; only inline execution is relaxed.
ADMIN_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace(
    "script-src 'self'", "script-src 'self' 'unsafe-inline'"
).replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")

# Swagger UI and ReDoc load their bundles from a CDN and Swagger initialises itself from an inline script, so the
# strict policy renders an empty page. Scoped to the docs paths, which are superuser-only outside development.
DOCS_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)

ADMIN_PREFIX = "/admin"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set standard security headers on every response.

    Adds Content-Security-Policy, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, and HSTS
    (production/staging only).
    """

    def __init__(self, app: ASGIApp, environment: str = "development", docs_paths: list[str] | None = None) -> None:
        super().__init__(app)
        self.environment = environment
        self.docs_paths = frozenset(path for path in (docs_paths or []) if path)

    def _policy_for(self, path: str) -> str:
        if path == ADMIN_PREFIX or path.startswith(f"{ADMIN_PREFIX}/"):
            return ADMIN_CONTENT_SECURITY_POLICY
        if path in self.docs_paths:
            return DOCS_CONTENT_SECURITY_POLICY
        return CONTENT_SECURITY_POLICY

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = self._policy_for(request.url.path)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        if self.environment in ("production", "staging"):
            response.headers["Strict-Transport-Security"] = f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains"

        return response
