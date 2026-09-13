"""The tool registry: how an internal tool plugs into the platform.

A tool module declares one :class:`ToolSpec` in ``tool.py`` and calls
:func:`register`. :func:`discover_tools` imports every package under
``src.modules.tools``, which runs those registrations, and
:func:`include_tool_routers` mounts each tool's router at its prefix. Adding a
tool therefore means adding a directory — no edits to shared wiring.
"""

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from ...infrastructure.logging import get_logger

logger = get_logger()

TOOLS_PACKAGE = "src.modules.tools"


@dataclass(frozen=True)
class ToolSpec:
    """Everything the platform needs to know about an internal tool."""

    name: str
    slug: str
    description: str
    route_prefix: str
    required_permission: str
    nav_label: str


_registry: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    """Register a tool.

    Re-registering the same slug replaces the previous spec.
    """
    _registry[spec.slug] = spec
    return spec


def clear_registry() -> None:
    """Drop all registered tools (tests only)."""
    _registry.clear()


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


def include_tool_routers(parent: APIRouter) -> None:
    """Mount ``router`` from each registered tool at the spec's route prefix."""
    for spec in registered_tools():
        try:
            module = importlib.import_module(f"{TOOLS_PACKAGE}.{spec.slug}.router")
        except Exception:
            logger.exception(f"Failed to import router for tool '{spec.slug}'")
            continue

        router = getattr(module, "router", None)
        if router is None:
            logger.error(f"Tool '{spec.slug}' has no 'router' attribute in router.py")
            continue

        parent.include_router(router, prefix=spec.route_prefix)


def tool_template_dirs() -> list[Path]:
    """Template directories contributed by tool modules, for the Jinja loader."""
    package_path = tools_package_path()
    if not package_path.is_dir():
        return []

    return [path for path in sorted(package_path.glob("*/templates")) if path.is_dir()]
