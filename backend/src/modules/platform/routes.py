"""Server-rendered platform pages: login, the tool launcher, and the audit log.

These are HTML routes, not API routes: they live outside ``/api/v1`` and return
templates. The JSON API for sessions stays where it was
(``/api/v1/auth/login``); this router only adds the browser-facing form so an
internal user has somewhere to log in.
"""

from typing import Annotated, Any

from crudauth.exceptions import UnauthorizedException
from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ...infrastructure.auth.setup import auth as crud_auth
from ...infrastructure.dependencies import AsyncSessionDep, OptionalUserDep
from ...infrastructure.logging import get_logger
from ...infrastructure.security import redact_identifier
from . import service
from .constants import AUDIT_PAGE_SIZE, PERM_AUDIT_READ
from .dependencies import ViewerContext, ViewerDep, require_page_permission
from .templating import render

logger = get_logger()

router = APIRouter(include_in_schema=False)

AuditViewerDep = Annotated[ViewerContext, Depends(require_page_permission(PERM_AUDIT_READ))]
EntityTypeFilter = Annotated[str | None, Query(max_length=100)]


def safe_next_path(next_url: str | None) -> str:
    """Only same-origin relative paths are accepted as post-login targets."""
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    if "\\" in next_url or any(ord(char) < 0x20 for char in next_url):
        return "/"
    return next_url


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: OptionalUserDep, next: str = "/", error: str | None = None) -> Any:
    """The login form.

    Already-authenticated users are sent to the launcher.
    """
    if user is not None:
        return RedirectResponse(url=safe_next_path(next), status_code=303)

    return render(request, "platform/login.html", context={"next": safe_next_path(next), "error": error})


@router.post("/login")
async def login_submit(
    request: Request,
    db: AsyncSessionDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Any:
    """Authenticate the form and start a session, then redirect to the launcher.

    Credential checking and lockout are crudauth's; this only adapts the browser form to the same session engine the API
    uses.
    """
    try:
        user = await crud_auth.authenticate_password(db, username, password, request=request)
    except Exception as exc:
        identifier = redact_identifier(username)
        logger.info(f"Failed browser login for {identifier}: {type(exc).__name__}")
        await service.record_failed_login(db, identifier)
        message = "Too many attempts. Try again later." if not isinstance(exc, UnauthorizedException) else None
        return render(
            request,
            "platform/login.html",
            context={"next": safe_next_path(next), "error": message or "Invalid username or password."},
            status_code=401,
        )

    session_id, csrf_token = await crud_auth.sessions.create_session(
        request,
        user_id=crud_auth.repo.user_id(user),
        metadata={"login_type": "password", "username": crud_auth.repo.get(user, "username")},
    )

    await service.record_login(db, crud_auth.repo.user_id(user))

    response = RedirectResponse(url=safe_next_path(next), status_code=303)
    crud_auth.sessions.set_session_cookies(response, session_id, csrf_token)
    return response


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSessionDep, viewer: ViewerDep) -> Response:
    """End the browser session (HTMX posts this, so CSRF rides in the header)."""
    session_id = request.cookies.get(crud_auth.sessions.session_cookie_name)
    if session_id:
        await crud_auth.sessions.revoke(session_id, owner_id=int(viewer.user["id"]))

    await service.record_logout(db, viewer.user)

    result = Response(status_code=204, headers={"HX-Redirect": "/login"})
    crud_auth.sessions.clear_session_cookies(result)
    return result


@router.get("/", response_class=HTMLResponse)
async def launcher(request: Request, viewer: ViewerDep) -> Any:
    """Home page: the tools this user may open, as cards."""
    return render(request, "platform/home.html", viewer=viewer)


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request, db: AsyncSessionDep, viewer: AuditViewerDep, entity_type: EntityTypeFilter = None
) -> Any:
    """The last 200 audit events, filterable by entity type."""
    events = await service.list_audit_events(db, entity_type=entity_type, limit=AUDIT_PAGE_SIZE)
    entity_types = await service.list_audit_entity_types(db)

    return render(
        request,
        "platform/audit.html",
        viewer=viewer,
        context={"events": events, "entity_types": entity_types, "selected_entity_type": entity_type or ""},
    )


@router.get("/audit/rows", response_class=HTMLResponse)
async def audit_rows(
    request: Request, db: AsyncSessionDep, viewer: AuditViewerDep, entity_type: EntityTypeFilter = None
) -> Any:
    """HTMX partial: just the table rows, for the entity-type filter."""
    events = await service.list_audit_events(db, entity_type=entity_type, limit=AUDIT_PAGE_SIZE)
    return render(request, "platform/_audit_rows.html", viewer=viewer, context={"events": events})
