from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from crudauth.exceptions import UnauthorizedException
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from ...infrastructure.dependencies import AsyncSessionDep
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
