"""Wire the platform into the FastAPI app: static files, pages, tool routers.

One call in ``interfaces/main.py`` mounts everything, so a new tool never needs
an edit here — :func:`discover_tools` finds it.
"""

from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ...infrastructure.request_context import RequestContextMiddleware
from .dependencies import LoginRequiredError
from .registry import discover_tools, include_tool_routers
from .routes import router as platform_router
from .templating import STATIC_DIR, refresh_template_loader


def setup_platform(app: FastAPI) -> None:
    """Mount the platform UI and every registered tool onto ``app``."""
    app.add_middleware(RequestContextMiddleware)

    discover_tools()
    refresh_template_loader()

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(LoginRequiredError)
    async def login_required_handler(request: Request, exc: LoginRequiredError) -> RedirectResponse:
        next_url = exc.next_url or request.url.path
        return RedirectResponse(url=f"/login?next={quote(next_url, safe='/')}", status_code=303)

    tools_router = APIRouter(include_in_schema=False)
    include_tool_routers(tools_router)

    app.include_router(platform_router)
    app.include_router(tools_router)
