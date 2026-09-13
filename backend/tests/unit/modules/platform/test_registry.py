"""The tool registry: what the launcher shows and what gets mounted."""

from types import SimpleNamespace

import pytest
from fastapi import APIRouter

from src.modules.platform.registry import (
    Permission,
    ToolSpec,
    clear_registry,
    get_tool,
    include_tool_api_routers,
    include_tool_routers,
    register,
    register_tool_admin_views,
    registered_tools,
    run_tool_seeds,
    tool_permissions,
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


def test_manifest_api_router_is_collected_under_its_prefix() -> None:
    api = APIRouter()

    @api.get("/evaluate")
    async def evaluate() -> dict[str, str]:
        return {"ok": "yes"}

    spec = make_spec("flags", "flags.read")
    register(ToolSpec(**{**spec.__dict__, "api": api, "api_prefix": "/flags"}))
    parent = APIRouter()

    include_tool_api_routers(parent)

    assert [route.path for route in parent.routes] == ["/flags/evaluate"]  # type: ignore[attr-defined]


def test_a_tool_without_an_api_contributes_no_routes() -> None:
    register(make_spec("kyc", "kyc.review"))
    parent = APIRouter()

    include_tool_api_routers(parent)

    assert parent.routes == []


def test_manifest_admin_views_are_registered_with_sqladmin() -> None:
    class CaseAdmin:
        pass

    spec = make_spec("kyc", "kyc.review")
    register(ToolSpec(**{**spec.__dict__, "admin_views": (CaseAdmin,)}))
    registered: list[type[object]] = []

    register_tool_admin_views(SimpleNamespace(add_view=registered.append))

    assert registered == [CaseAdmin]


def test_tool_permissions_are_collected_from_every_manifest() -> None:
    kyc = make_spec("kyc", "kyc.review")
    flags = make_spec("flags", "flags.read")
    register(ToolSpec(**{**kyc.__dict__, "permissions": (Permission("kyc.review", "Review"),)}))
    register(ToolSpec(**{**flags.__dict__, "permissions": (Permission("flags.read", "Read"),)}))

    assert {permission.name for permission in tool_permissions()} == {"kyc.review", "flags.read"}


@pytest.mark.asyncio
async def test_run_tool_seeds_runs_every_declared_seed_and_skips_the_rest() -> None:
    calls: list[str] = []

    async def seed_kyc(db: object) -> None:
        calls.append("kyc")

    kyc = make_spec("kyc", "kyc.review")
    register(ToolSpec(**{**kyc.__dict__, "seed": seed_kyc}))
    register(make_spec("flags", "flags.read"))

    seeded = await run_tool_seeds(None)  # type: ignore[arg-type]

    assert calls == ["kyc"]
    assert seeded == ["kyc"]
