"""Unit tests for the Feature Flags tool: write permission, audit, evaluation."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from crudauth.exceptions import ForbiddenException, UnauthorizedException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.modules.api_keys.dependencies import require_api_key
from src.modules.api_keys.enums import KeyPermissionAction, KeyPermissionResource
from src.modules.api_keys.schemas import APIKeyValidationResponse
from src.modules.common.exceptions import ResourceExistsError
from src.modules.platform.admin import PermissionGatedView
from src.modules.platform.constants import (
    ADMIN_PERMISSIONS,
    ANALYST_PERMISSIONS,
    PERM_FLAGS_WRITE,
    PERM_PLATFORM_ADMIN,
)
from src.modules.platform.crud import crud_audit_events
from src.modules.platform.dependencies import ViewerContext, require_page_permission
from src.modules.tools.flags import service
from src.modules.tools.flags.admin import FlagAdmin

pytestmark = pytest.mark.asyncio

ANALYST = set(ANALYST_PERMISSIONS)
ADMIN = set(ADMIN_PERMISSIONS)


def viewer_with(permissions: set[str], user: dict[str, Any] | None = None) -> ViewerContext:
    return ViewerContext(user=user or {"id": 1, "is_superuser": False}, roles=[], permissions=permissions)


async def make_flag(db: AsyncSession, actor: dict, key: str, **kwargs: Any) -> dict[str, Any]:
    return await service.create_flag(db, actor, ADMIN, key=key, **kwargs)


async def actions_for(db: AsyncSession, flag_id: int) -> list[str]:
    events = await crud_audit_events.get_multi(db=db, entity_type=service.ENTITY_TYPE, entity_id=str(flag_id))
    return [event["action"] for event in events["data"]]


async def test_page_permission_rejects_non_holder() -> None:
    dependency = require_page_permission("flags.read")

    with pytest.raises(ForbiddenException, match="flags.read"):
        await dependency(viewer=viewer_with(set()))


async def test_create_records_an_audit_event(db_session: AsyncSession, test_user: dict) -> None:
    flag = await make_flag(db_session, test_user, "checkout.new-risk-engine", description="New engine")

    assert flag["enabled"] is False
    assert flag["updated_by"] == test_user["id"]
    assert "flags.flag.created" in await actions_for(db_session, flag["id"])


async def test_create_rejects_a_duplicate_key(db_session: AsyncSession, test_user: dict) -> None:
    await make_flag(db_session, test_user, "payouts.instant")

    with pytest.raises(ResourceExistsError, match="already exists"):
        await make_flag(db_session, test_user, "payouts.instant")


async def test_toggle_flips_the_flag_and_audits_before_and_after(db_session: AsyncSession, test_user: dict) -> None:
    flag = await make_flag(db_session, test_user, "ledger.async-writes")

    toggled = await service.toggle_flag(db_session, test_user, ADMIN, flag["id"])

    assert toggled["enabled"] is True
    events = await crud_audit_events.get_multi(db=db_session, entity_type=service.ENTITY_TYPE, entity_id=str(flag["id"]))
    toggle_event = next(event for event in events["data"] if event["action"] == "flags.flag.toggled")
    assert toggle_event["before"]["enabled"] is False
    assert toggle_event["after"]["enabled"] is True


async def test_update_changes_only_the_fields_given(db_session: AsyncSession, test_user: dict) -> None:
    flag = await make_flag(db_session, test_user, "search.rerank", description="Rerank results", rollout_percent=100)

    updated = await service.update_flag(db_session, test_user, ADMIN, flag["id"], rollout_percent=25)

    assert updated["rollout_percent"] == 25
    assert updated["description"] == "Rerank results"
    assert "flags.flag.updated" in await actions_for(db_session, flag["id"])


async def test_writes_require_the_write_permission(db_session: AsyncSession, test_user: dict) -> None:
    flag = await make_flag(db_session, test_user, "fraud.manual-review")

    assert PERM_FLAGS_WRITE not in ANALYST
    for change in (
        lambda: service.create_flag(db_session, test_user, ANALYST, key="analyst.attempt"),
        lambda: service.update_flag(db_session, test_user, ANALYST, flag["id"], rollout_percent=10),
        lambda: service.toggle_flag(db_session, test_user, ANALYST, flag["id"]),
    ):
        with pytest.raises(ForbiddenException, match=PERM_FLAGS_WRITE):
            await change()


def test_evaluate_is_false_when_the_flag_is_disabled() -> None:
    flag = {"key": "k", "enabled": False, "rollout_percent": 100}

    assert service.evaluate(flag, "user-1") == (False, "flag disabled")


def test_evaluate_is_true_at_full_rollout() -> None:
    flag = {"key": "k", "enabled": True, "rollout_percent": 100}

    enabled, _ = service.evaluate(flag, "user-1")
    assert enabled is True


def test_evaluate_is_deterministic_per_subject() -> None:
    flag = {"key": "k", "enabled": True, "rollout_percent": 50}

    results = {service.evaluate(flag, "user-42")[0] for _ in range(5)}
    assert len(results) == 1


def test_evaluate_splits_subjects_roughly_by_rollout_percent() -> None:
    flag = {"key": "checkout.new-risk-engine", "enabled": True, "rollout_percent": 30}

    on = sum(service.evaluate(flag, f"user-{index}")[0] for index in range(1000))
    assert 200 < on < 400


def test_buckets_differ_between_flags_for_the_same_subject() -> None:
    subject = "user-7"

    buckets = {service.bucket_of(key, subject) for key in ("flag.one", "flag.two", "flag.three")}
    assert len(buckets) > 1


async def test_evaluate_endpoint_rejects_a_missing_api_key(db_session: AsyncSession) -> None:
    dependency = require_api_key(KeyPermissionResource.WILDCARD, KeyPermissionAction.READ)

    with pytest.raises(UnauthorizedException, match="X-API-Key"):
        await dependency(db=db_session, service=_StubKeyService(valid=True), api_key=None)


async def test_evaluate_endpoint_rejects_an_invalid_api_key(db_session: AsyncSession) -> None:
    dependency = require_api_key(KeyPermissionResource.WILDCARD, KeyPermissionAction.READ)

    with pytest.raises(UnauthorizedException, match="Invalid API key"):
        await dependency(db=db_session, service=_StubKeyService(valid=False), api_key="fai_deadbeef_nope")


async def test_evaluate_endpoint_accepts_a_valid_api_key(db_session: AsyncSession) -> None:
    dependency = require_api_key(KeyPermissionResource.WILDCARD, KeyPermissionAction.READ)

    caller = await dependency(db=db_session, service=_StubKeyService(valid=True), api_key="fai_deadbeef_ok")

    assert caller.is_valid is True


class _StubKeyService:
    """Stands in for APIKeyService so the dependency is tested without hashing a real key."""

    def __init__(self, valid: bool) -> None:
        self.valid = valid

    async def validate_api_key(self, api_key: str, resource: str, action: str, db: AsyncSession) -> APIKeyValidationResponse:
        if not self.valid:
            return APIKeyValidationResponse(is_valid=False, error_message="Invalid API key")
        return APIKeyValidationResponse(is_valid=True, api_key_id=1, user_id=1)


async def test_toggle_bumps_updated_at(db_session: AsyncSession, test_user: dict) -> None:
    flag = await make_flag(db_session, test_user, "dashboard.new-nav")

    toggled = await service.toggle_flag(db_session, test_user, ADMIN, flag["id"])

    assert toggled["updated_at"] is not None
    assert toggled["updated_at"] > flag["updated_at"]


def test_admin_view_is_permission_gated() -> None:
    """Without ``PermissionGatedView`` the ``required_permission`` attribute is inert."""
    assert issubclass(FlagAdmin, PermissionGatedView)
    assert FlagAdmin.required_permission == PERM_PLATFORM_ADMIN

    open_request = SimpleNamespace(session={"user_id": 7, "permissions": ["flags.read"]})
    admin_request = SimpleNamespace(session={"user_id": 7, "permissions": [PERM_PLATFORM_ADMIN]})

    assert FlagAdmin().is_accessible(cast(Request, open_request)) is False
    assert FlagAdmin().is_visible(cast(Request, open_request)) is False
    assert FlagAdmin().is_accessible(cast(Request, admin_request)) is True
