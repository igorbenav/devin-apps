"""Jinja setup shared by the platform and every tool module.

Tool templates live next to their module
(``modules/tools/<slug>/templates/<slug>/list.html``) and are found through a
``ChoiceLoader``, so a tool ships its UI in its own directory and still extends
the shared layout with ``{% extends "platform/base.html" %}``.
"""

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from ...infrastructure.config.settings import settings
from .dependencies import ViewerContext
from .registry import registered_tools, tool_template_dirs, tools_for

PLATFORM_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


def build_templates() -> Jinja2Templates:
    """Jinja2Templates loading platform templates plus every tool's templates."""
    loaders = [FileSystemLoader(str(PLATFORM_TEMPLATES_DIR))]
    loaders += [FileSystemLoader(str(path)) for path in tool_template_dirs()]

    templates = Jinja2Templates(directory=str(PLATFORM_TEMPLATES_DIR))
    templates.env.loader = ChoiceLoader(loaders)
    return templates


templates = build_templates()


def refresh_template_loader() -> None:
    """Rebuild the loader after tools are discovered (or generated in dev)."""
    loaders = [FileSystemLoader(str(PLATFORM_TEMPLATES_DIR))]
    loaders += [FileSystemLoader(str(path)) for path in tool_template_dirs()]
    templates.env.loader = ChoiceLoader(loaders)


ISSUE_LABEL = "tool-bug"

ISSUE_BODY = """**What happened**

<!-- what you did, and what the page did instead -->

**Tool:** {tool}
**Page:** {page}
**Reported by:** {reporter}
"""


def report_issue_url(request: Request, viewer: ViewerContext | None) -> str:
    """A prefilled issue for the page the viewer is on.

    The label is what an automation watches for, so a report from inside a tool arrives as a Devin prompt with the tool,
    page and reporter already in it — the context a bug report usually loses.
    """
    page = request.url.path
    tool = next((spec.name for spec in registered_tools() if page.startswith(spec.route_prefix)), "Platform")
    query = urlencode(
        {
            "labels": ISSUE_LABEL,
            "title": f"[{tool}] ",
            "body": ISSUE_BODY.format(tool=tool, page=page, reporter=viewer.user["username"] if viewer else "unknown"),
        }
    )
    return f"{settings.ISSUE_TRACKER_NEW_ISSUE_URL}?{query}"


def render(
    request: Request,
    template_name: str,
    viewer: ViewerContext | None = None,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> Any:
    """Render a template with the shared layout context already filled in."""
    payload: dict[str, Any] = {
        "viewer": viewer,
        "permissions": viewer.permissions if viewer else set(),
        "nav_tools": tools_for(viewer.permissions) if viewer else [],
        "all_tools": registered_tools(),
        "report_issue_url": report_issue_url(request, viewer),
    }
    payload.update(context or {})

    return templates.TemplateResponse(request=request, name=template_name, context=payload, status_code=status_code)
