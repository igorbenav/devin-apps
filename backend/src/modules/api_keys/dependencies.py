from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from crudauth.exceptions import UnauthorizedException
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from ...infrastructure.config import get_settings
from ...infrastructure.dependencies import AsyncSessionDep
from ...infrastructure.rate_limit.exceptions import RateLimitException
from ...infrastructure.rate_limit.provider import increment_and_check
from .enums import KeyPermissionAction, KeyPermissionResource
from .schemas import APIKeyValidationResponse
from .service import APIKeyService


def get_api_key_service() -> APIKeyService:
    return APIKeyService()


APIKeyServiceDep = Annotated[APIKeyService, Depends(get_api_key_service)]

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    resource: KeyPermissionResource,
    action: KeyPermissionAction = KeyPermissionAction.READ,
) -> Callable[..., Coroutine[Any, Any, APIKeyValidationResponse]]:
    """Authenticate a request by ``X-API-Key`` instead of a session.

    For service-to-service routes only; browser routes use the session dependencies. Apply it per route, never as a
    global dependency.
    """

    async def dependency(
        db: AsyncSessionDep,
        service: APIKeyServiceDep,
        api_key: Annotated[str | None, Security(api_key_header)] = None,
    ) -> APIKeyValidationResponse:
        if not api_key:
            raise UnauthorizedException("An X-API-Key header is required")

        validation = await service.validate_api_key(api_key, resource, action, db)
        if not validation.is_valid:
            raise UnauthorizedException(validation.error_message or "Invalid API key")
        return validation

    return dependency


async def enforce_api_key_rate_limit(caller: APIKeyValidationResponse, *, limit: int, period: int) -> None:
    """Rate limit a route per API key.

    The shipped ``check_rate_limit`` buckets by session user or client IP and reads tier limits, neither of which fits
    a key-authenticated service route: every caller shares one IP behind a cluster egress. This buckets by key id.

    Enforcement needs the rate limiter backend, which is only registered when ``RATE_LIMITER_ENABLED``; with it off the
    route is unlimited, the same opt-in posture as the rest of the repo.
    """
    settings = get_settings()
    if not settings.RATE_LIMITER_ENABLED:
        return

    _, is_limited = await increment_and_check(
        key=f"ratelimit:apikey:{caller.api_key_id}",
        limit=limit,
        period=period,
        fail_open=settings.RATE_LIMITER_FAIL_OPEN,
    )
    if is_limited:
        raise RateLimitException(f"Rate limit exceeded for this API key. Try again in {period} seconds.")
