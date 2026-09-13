"""The tool registry: how an internal tool plugs into the platform.

A tool module declares one :class:`ToolSpec` in ``tool.py`` and calls
:func:`register`. The spec is the whole contract: pages, JSON API, admin views,
the permissions the tool owns and its demo seed all hang off it, and the
platform *collects* them (:func:`include_tool_routers`,
:func:`include_tool_api_routers`, :func:`register_tool_admin_views`,
:func:`permission_catalog`, :func:`run_tool_seeds`). Adding a tool means adding
a directory: no shared file names a tool, and nothing under ``interfaces/``
imports one.

Discovery scans ``src/modules/tools/*``. Tools that later become installed
packages can be found the same way through an entry point without changing any
of the collection functions.
"""

import importlib
import pkgutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from ...infrastructure.logging import get_logger

logger = get_logger()

TOOLS_PACKAGE = "src.modules.tools"

SeedCallable = Callable[[AsyncSession], Awaitable[None]]


@dataclass(frozen=True)
class Permission:
    """A flat permission string and what holding it allows.

    Tools declare their own; the platform only collects them, so adding a permission never means editing a shared
    catalog.
    """

    name: str
    description: str


@dataclass(frozen=True)
class ToolSpec:
    """Everything a tool contributes to the platform, declared in one place.

    Only ``pages`` is required beyond the identity fields: a tool with no JSON
    API, no admin views and no seed simply leaves those empty.
    """

    name: str
    slug: str
    description: str
    route_prefix: str
    required_permission: str
    nav_label: str
    pages: APIRouter | None = None
    api: APIRouter | None = None
    api_prefix: str | None = None
    admin_views: tuple[type[Any], ...] = ()
    permissions: tuple[Permission, ...] = field(default_factory=tuple)
    seed: SeedCallable | None = None


_registry: dict[str, ToolSpec] = {}
_discovered = False


def register(spec: ToolSpec) -> ToolSpec:
    """Register a tool.

    Re-registering the same slug replaces the previous spec.
    """
    _registry[spec.slug] = spec
    return spec


def clear_registry() -> None:
    """Drop all registered tools (tests only)."""
    global _discovered
    _registry.clear()
    _discovered = False


def registered_tools() -> list[ToolSpec]:
    """All registered tools, ordered by nav label."""
    return sorted(_registry.values(), key=lambda spec: spec.nav_label.lower())


def tools_for(permissions: set[str]) -> list[ToolSpec]:
    """The registered tools whose required permission the caller holds."""
    return [spec for spec in registered_tools() if spec.required_permission in permissions]


def get_tool(slug: str) -> ToolSpec | None:
    """The spec registered under ``slug``, if any."""
    return _registry.get(slug)


def tools_package_path() -> Path:
    """Filesystem path of the ``tools`` package."""
    return Path(__file__).resolve().parent.parent / "tools"


def discover_tools() -> list[ToolSpec]:
    """Import every tool package so its ``tool.py`` registers its spec."""
    global _discovered
    _discovered = True

    package_path = tools_package_path()
    if not package_path.is_dir():
        return []

    for module_info in pkgutil.iter_modules([str(package_path)]):
        if not module_info.ispkg:
            continue
        try:
            importlib.import_module(f"{TOOLS_PACKAGE}.{module_info.name}.tool")
        except Exception:
            logger.exception(f"Failed to register tool '{module_info.name}'")

    return registered_tools()


def ensure_discovered() -> None:
    """Discover tools if nothing has yet.

    Collection happens at import time in a few places (the API router is built
    while ``interfaces`` is imported, before the app's startup code runs), so
    every collector calls this instead of relying on call order.
    """
    if not _discovered:
        discover_tools()


def include_tool_routers(parent: APIRouter) -> None:
    """Mount each tool's HTMX pages at its route prefix."""
    ensure_discovered()
    for spec in registered_tools():
        if spec.pages is None:
            logger.error(f"Tool '{spec.slug}' declares no pages router")
            continue
        parent.include_router(spec.pages, prefix=spec.route_prefix)


def include_tool_api_routers(parent: APIRouter) -> None:
    """Mount the JSON API of every tool that declares one.

    Called from ``interfaces/api/v1`` so that layer never imports a tool.
    """
    ensure_discovered()
    for spec in registered_tools():
        if spec.api is None:
            continue
        parent.include_router(spec.api, prefix=spec.api_prefix or f"/{spec.slug}")


def register_tool_admin_views(admin: Any) -> None:
    """Register every tool's SQLAdmin views with the admin interface."""
    ensure_discovered()
    for spec in registered_tools():
        for view in spec.admin_views:
            admin.add_view(view)


def tool_permissions() -> tuple[Permission, ...]:
    """Every permission declared by a registered tool."""
    ensure_discovered()
    return tuple(permission for spec in registered_tools() for permission in spec.permissions)


async def run_tool_seeds(db: AsyncSession) -> list[str]:
    """Run the demo seed of every tool that declares one; returns the slugs seeded.

    Demo data only — the seed scripts are guarded against production, not this.
    """
    ensure_discovered()
    seeded = []
    for spec in registered_tools():
        if spec.seed is None:
            continue
        await spec.seed(db)
        seeded.append(spec.slug)
    return seeded


def tool_template_dirs() -> list[Path]:
    """Template directories contributed by tool modules, for the Jinja loader."""
    package_path = tools_package_path()
    if not package_path.is_dir():
        return []

    return [path for path in sorted(package_path.glob("*/templates")) if path.is_dir()]
