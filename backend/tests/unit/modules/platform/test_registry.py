"""The tool registry: what the launcher shows and what gets mounted."""

import pytest
from fastapi import APIRouter

from src.modules.platform.registry import (
    ToolSpec,
    clear_registry,
    get_tool,
    include_tool_routers,
    register,
    registered_tools,
    tools_for,
)


def make_spec(slug: str, permission: str, label: str | None = None) -> ToolSpec:
    return ToolSpec(
        name=label or slug.title(),
        slug=slug,
        description=f"{slug} tool",
        route_prefix=f"/tools/{slug}",
        required_permission=permission,
        nav_label=label or slug.title(),
    )


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_tools_are_listed_by_nav_label() -> None:
    register(make_spec("zeta", "zeta.use"))
    register(make_spec("alpha", "alpha.use"))

    assert [spec.slug for spec in registered_tools()] == ["alpha", "zeta"]


def test_registering_the_same_slug_replaces_the_spec() -> None:
    register(make_spec("kyc", "kyc.review", label="Old"))
    register(make_spec("kyc", "kyc.review", label="New"))

    assert len(registered_tools()) == 1
    spec = get_tool("kyc")
    assert spec is not None and spec.nav_label == "New"


def test_launcher_only_sees_tools_the_user_may_open() -> None:
    register(make_spec("kyc", "kyc.review"))
    register(make_spec("flags", "flags.write"))

    assert [spec.slug for spec in tools_for({"kyc.review"})] == ["kyc"]
    assert tools_for(set()) == []
    assert len(tools_for({"kyc.review", "flags.write"})) == 2


def test_missing_tool_module_does_not_break_mounting() -> None:
    register(make_spec("not_a_real_module", "x.use"))
    parent = APIRouter()

    include_tool_routers(parent)

    assert parent.routes == []
