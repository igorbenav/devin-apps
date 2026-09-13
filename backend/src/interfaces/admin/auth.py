"""Authentication backend for SQLAdmin.

Two ways in: the break-glass ``ADMIN_USERNAME``/``ADMIN_PASSWORD`` pair from
settings (no platform user behind it, so the views treat it as a superuser), or
a normal platform user who holds ``platform.admin`` — whose session carries the
permissions the views gate on, so /admin follows the same permission model as
the rest of the platform instead of a second, parallel one.
"""

import hmac

from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from ...infrastructure.auth.setup import auth as crud_auth
from ...infrastructure.config.settings import get_settings
from ...infrastructure.database.session import local_session
from ...infrastructure.logging import get_logger
from ...infrastructure.security import redact_identifier
from ...modules.platform.constants import PERM_PLATFORM_ADMIN
from ...modules.platform.service import get_permissions_for_user, record_login, record_logout
from ...modules.user.models import User

logger = get_logger()


def _credential_matches(submitted: object, expected: str) -> bool:
    """Compare a submitted credential against the configured one in constant time."""
    if not isinstance(submitted, str):
        return False
    return hmac.compare_digest(submitted.encode(), expected.encode())


class AdminAuth(AuthenticationBackend):
    """Session-based authentication for the admin interface."""

    async def login(self, request: Request) -> bool:
        """Validate login credentials and create session."""
        form = await request.form()
        settings = get_settings()
        username = form.get("username")
        password = form.get("password")

        if settings.ADMIN_USERNAME and settings.ADMIN_PASSWORD:
            username_matches = _credential_matches(username, settings.ADMIN_USERNAME)
            password_matches = _credential_matches(password, settings.ADMIN_PASSWORD)
            if username_matches and password_matches:
                request.session.update({"admin_authenticated": True})
                async with local_session() as db:
                    await record_login(db, None, method="admin_break_glass")
                return True

        if not isinstance(username, str) or not isinstance(password, str):
            return False

        return await self._login_platform_user(request, username, password)

    async def _login_platform_user(self, request: Request, username: str, password: str) -> bool:
        """Log in a platform user that holds ``platform.admin`` (or is a superuser)."""
        async with local_session() as db:
            try:
                user = await crud_auth.authenticate_password(db, username, password, request=request)
            except Exception as exc:
                logger.info(f"Failed admin login for {redact_identifier(username)}: {type(exc).__name__}")
                return False

            user_id = int(crud_auth.repo.user_id(user))
            is_superuser = bool(crud_auth.repo.get(user, "is_superuser"))
            permissions = await get_permissions_for_user(db, user_id, is_superuser=is_superuser)

        if not is_superuser and PERM_PLATFORM_ADMIN not in permissions:
            logger.info(f"Admin login denied for user {user_id}: missing {PERM_PLATFORM_ADMIN}")
            return False

        request.session.update(
            {
                "admin_authenticated": True,
                "user_id": user_id,
                "is_superuser": is_superuser,
                "permissions": sorted(permissions),
            }
        )
        async with local_session() as db:
            await record_login(db, user_id, method="admin")
        return True

    async def logout(self, request: Request) -> bool:
        """Clear the admin session."""
        user_id = request.session.get("user_id")
        if request.session.get("admin_authenticated", False):
            async with local_session() as db:
                await record_logout(
                    db,
                    int(user_id) if user_id is not None else None,
                    method="admin" if user_id is not None else "admin_break_glass",
                )
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        """Check if the current request is authenticated, re-resolving permissions.

        SQLAdmin's ``is_accessible`` is sync and cannot query, so the views read permissions off the session. Resolving
        them here — on every admin request — keeps that snapshot one request old at most, so revoking a role or deleting
        a user takes effect immediately instead of at the next login.
        """
        if not request.session.get("admin_authenticated", False):
            return False

        user_id = request.session.get("user_id")
        if user_id is None:
            return True

        async with local_session() as db:
            user = await db.get(User, int(user_id))
            if user is None or user.is_deleted:
                request.session.clear()
                return False

            permissions = await get_permissions_for_user(db, int(user_id), is_superuser=user.is_superuser)

        if not user.is_superuser and PERM_PLATFORM_ADMIN not in permissions:
            logger.info(f"Admin access revoked mid-session for user {user_id}: missing {PERM_PLATFORM_ADMIN}")
            request.session.clear()
            return False

        request.session.update({"is_superuser": user.is_superuser, "permissions": sorted(permissions)})
        return True
