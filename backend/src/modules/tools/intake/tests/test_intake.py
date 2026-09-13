"""Unit tests for the Tool Requests tool: validation, limits, audit, dispatch."""

from typing import Any

import httpx
import pytest
from crudauth.exceptions import ForbiddenException
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.common.exceptions import ValidationError
from src.modules.platform.crud import crud_audit_events
from src.modules.platform.dependencies import ViewerContext, require_page_permission
from src.modules.tools.intake import devin, service
from src.modules.tools.intake.permissions import PERM_REQUEST_ADMIN, REQUIRED_PERMISSION
from src.modules.tools.intake.prompt import build_prompt
from src.modules.tools.intake.router import _may_act_on
from src.modules.tools.intake.schemas import ToolRequestBrief

pytestmark = pytest.mark.asyncio

BRIEF = {
    "title": "Chargeback review queue",
    "slug_hint": "chargebacks",
    "users": "Payment operations analysts",
    "decision": "Decide whether to contest a chargeback before the deadline",
    "today": "A shared spreadsheet",
    "states": "new -> investigating -> contested | accepted",
    "must_never_happen": "The investigator accepts their own case",
    "provable": "Who decided, for the auditors",
    "data_sources": "PSP webhook export",
    "volume": "40 a day, 6 analysts",
    "success": "No missed deadlines in a month",
    "out_of_scope": "Writing decisions back to the PSP",
}


def brief(**overrides: Any) -> ToolRequestBrief:
    return ToolRequestBrief(**{**BRIEF, **overrides})


def viewer_with(permissions: set[str], user_id: int = 1) -> ViewerContext:
    return ViewerContext(user={"id": user_id, "is_superuser": False}, roles=[], permissions=permissions)


async def actions_for(db: AsyncSession, request_id: int) -> list[str]:
    events = await crud_audit_events.get_multi(db=db, entity_type=service.ENTITY_TYPE, entity_id=str(request_id))
    return [event["action"] for event in events["data"]]


def unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devin.settings, "DEVIN_API_KEY", "")


def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devin.settings, "DEVIN_API_KEY", "devin-key")
    monkeypatch.setattr(devin.settings, "DEVIN_TOOL_PLAYBOOK_ID", "playbook-123")
    monkeypatch.setattr(devin.settings, "DEVIN_MAX_ACU_LIMIT", 7)


async def test_page_permission_rejects_non_holder() -> None:
    dependency = require_page_permission(REQUIRED_PERMISSION)

    with pytest.raises(ForbiddenException, match=REQUIRED_PERMISSION):
        await dependency(viewer=viewer_with(set()))


async def test_brief_rejects_a_reserved_slug() -> None:
    with pytest.raises(PydanticValidationError, match="reserved"):
        brief(slug_hint="admin")


async def test_brief_rejects_a_slug_that_is_not_a_module_name() -> None:
    with pytest.raises(PydanticValidationError):
        brief(slug_hint="Charge Backs")


async def test_submit_records_the_brief_and_an_audit_event(
    db_session: AsyncSession, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured(monkeypatch)

    created = await service.submit_request(db_session, test_user, brief())

    assert created["title"] == BRIEF["title"]
    assert created["requester_user_id"] == test_user["id"]
    assert "intake.request.submitted" in await actions_for(db_session, created["id"])


async def test_submit_without_an_api_key_leaves_the_request_queued(
    db_session: AsyncSession, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured(monkeypatch)

    created = await service.submit_request(db_session, test_user, brief())

    assert created["status"] == "queued"
    assert created["session_id"] is None
    assert "intake.request.dispatched" not in await actions_for(db_session, created["id"])


async def test_submit_is_rate_limited_per_requester(
    db_session: AsyncSession, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured(monkeypatch)
    for index in range(service.MAX_REQUESTS_PER_DAY):
        await service.submit_request(db_session, test_user, brief(slug_hint=f"tool-{index}"))

    with pytest.raises(ValidationError, match="paid Devin session"):
        await service.submit_request(db_session, test_user, brief(slug_hint="one-too-many"))


async def test_dispatch_sends_the_playbook_tags_and_acu_cap(
    db_session: AsyncSession, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured(monkeypatch)
    created = await service.submit_request(db_session, test_user, brief())
    configured(monkeypatch)
    sent: dict[str, Any] = {}

    async def fake_post(self: Any, path: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        sent.update({"path": path, "json": json, "headers": headers})
        return httpx.Response(
            200,
            json={"session_id": "devin-abc", "url": "https://app.devin.ai/sessions/abc"},
            request=httpx.Request("POST", path),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    dispatched = await service.dispatch_request(db_session, test_user, created["id"])

    assert sent["path"] == devin.CREATE_SESSION_PATH
    assert sent["json"]["tags"] == ["tool:chargebacks", "source:intake"]
    assert sent["json"]["max_acu_limit"] == 7
    assert sent["json"]["playbook_id"] == "playbook-123"
    assert dispatched["status"] == "dispatched"
    assert dispatched["session_url"] == "https://app.devin.ai/sessions/abc"
    assert "intake.request.dispatched" in await actions_for(db_session, created["id"])


async def test_dispatch_never_puts_the_api_key_or_response_body_in_the_stored_error(
    db_session: AsyncSession, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured(monkeypatch)
    created = await service.submit_request(db_session, test_user, brief())
    configured(monkeypatch)

    async def fake_post(self: Any, path: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(
            401, json={"detail": "bad key devin-key", "prompt": json["prompt"]}, request=httpx.Request("POST", path)
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    failed = await service.dispatch_request(db_session, test_user, created["id"])

    assert failed["status"] == "failed"
    assert failed["dispatch_error"] == "Devin API returned 401"
    assert "devin-key" not in failed["dispatch_error"]
    assert "intake.request.dispatch_failed" in await actions_for(db_session, created["id"])


async def test_dispatch_refuses_to_start_a_second_session(
    db_session: AsyncSession, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured(monkeypatch)
    created = await service.submit_request(db_session, test_user, brief())
    configured(monkeypatch)

    async def fake_post(self: Any, path: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(
            200,
            json={"session_id": "devin-abc", "url": "https://app.devin.ai/sessions/abc"},
            request=httpx.Request("POST", path),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await service.dispatch_request(db_session, test_user, created["id"])

    with pytest.raises(ValidationError, match="already has a session"):
        await service.dispatch_request(db_session, test_user, created["id"])


def test_only_the_requester_or_an_admin_may_see_a_request() -> None:
    stored = {"requester_user_id": 7}

    assert _may_act_on(stored, viewer_with({REQUIRED_PERMISSION}, user_id=7))
    assert not _may_act_on(stored, viewer_with({REQUIRED_PERMISSION}, user_id=8))
    assert _may_act_on(stored, viewer_with({REQUIRED_PERMISSION, PERM_REQUEST_ADMIN}, user_id=8))


def test_prompt_carries_every_answer_and_the_generator_command() -> None:
    prompt = build_prompt({**BRIEF, "id": 1}, "reviewer")

    assert "bp new tool chargebacks" in prompt
    for answer in BRIEF.values():
        assert answer in prompt
