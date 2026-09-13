"""The JSON API other services call to evaluate a flag.

Unlike every other tool route this is authenticated by API key, not by a
session: the callers are backend services, not browsers.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ....infrastructure.dependencies import AsyncSessionDep
from ...api_keys.dependencies import require_api_key
from ...api_keys.enums import KeyPermissionAction, KeyPermissionResource
from ...api_keys.schemas import APIKeyValidationResponse
from . import service
from .schemas import KEY_MAX_LENGTH, FlagEvaluation

SUBJECT_MAX_LENGTH = 200

router = APIRouter(tags=["flags"])

CallerDep = Annotated[
    APIKeyValidationResponse,
    Depends(require_api_key(KeyPermissionResource.WILDCARD, KeyPermissionAction.READ)),
]


@router.get("/evaluate", response_model=FlagEvaluation)
async def evaluate_flag(
    db: AsyncSessionDep,
    caller: CallerDep,
    key: Annotated[str, Query(description="The flag key to evaluate", max_length=KEY_MAX_LENGTH)],
    subject: Annotated[str, Query(description="Stable identifier the rollout is bucketed by", max_length=SUBJECT_MAX_LENGTH)],
) -> FlagEvaluation:
    """Whether ``key`` is on for ``subject``, and why."""
    flag = await service.get_flag_by_key(db, key)
    enabled, reason = service.evaluate(flag, subject)
    return FlagEvaluation(key=key, enabled=enabled, reason=reason)
