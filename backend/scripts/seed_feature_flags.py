"""Seed demo feature flags and an API key for the seeded admin.

Idempotent by flag key: re-running leaves existing flags untouched. The API key
is printed once, at the end — it is never stored in plaintext, so copy it from
the script output rather than looking for it in the database.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.infrastructure.database.initialize import close_database  # noqa: E402
from src.infrastructure.database.session import local_session  # noqa: E402
from src.infrastructure.logging import get_logger  # noqa: E402
from src.modules.api_keys.crud import crud_api_keys, crud_key_permissions  # noqa: E402
from src.modules.api_keys.enums import KeyPermissionAction, KeyPermissionResource  # noqa: E402
from src.modules.api_keys.schemas import APIKeyCreate, KeyPermissionCreate  # noqa: E402
from src.modules.api_keys.service import APIKeyService  # noqa: E402
from src.modules.platform.constants import ADMIN_PERMISSIONS  # noqa: E402
from src.modules.tools.flags import service  # noqa: E402
from src.modules.tools.flags.crud import crud_flags  # noqa: E402
from src.modules.user.service import UserService  # noqa: E402

logger = get_logger()

ADMIN_USERNAME = "toolsadmin"
API_KEY_NAME = "flag-evaluation-demo"

# key, description, enabled, rollout_percent
FLAGS: list[tuple[str, str, bool, int]] = [
    ("checkout.new-risk-engine", "Route checkout through the new risk engine", True, 100),
    ("payouts.instant", "Allow instant payouts for low-risk merchants", True, 25),
    ("kyc.auto-approve-low-risk", "Auto-approve KYC cases scoring under 20", False, 0),
    ("ledger.async-writes", "Write ledger entries asynchronously", True, 50),
    ("support.copilot", "Show the support copilot panel to agents", False, 100),
    ("dashboard.new-nav", "New left-hand navigation in the customer dashboard", True, 10),
]


async def _admin_user(db: AsyncSession) -> dict:
    user = await UserService().get_by_username(ADMIN_USERNAME, db)
    if user is None:
        raise RuntimeError(f"User '{ADMIN_USERNAME}' not found — run scripts.setup_initial_data first")
    return dict(user)


async def _seed_flags(db: AsyncSession, admin: dict) -> int:
    created = 0
    permissions = set(ADMIN_PERMISSIONS)

    for key, description, enabled, rollout_percent in FLAGS:
        if await crud_flags.exists(db=db, key=key):
            continue

        flag = await service.create_flag(
            db,
            admin,
            permissions,
            key=key,
            description=description,
            rollout_percent=rollout_percent,
        )
        if enabled:
            await service.toggle_flag(db, admin, permissions, flag["id"])
        created += 1

    return created


async def _seed_api_key(db: AsyncSession, admin: dict) -> str | None:
    """Create the demo evaluation key, or skip if one already exists."""
    if await crud_api_keys.exists(db=db, user_id=admin["id"], name=API_KEY_NAME):
        return None

    key_service = APIKeyService()
    created = await key_service.create_api_key(
        user_id=int(admin["id"]),
        key_data=APIKeyCreate(name=API_KEY_NAME),
        db=db,
    )
    await crud_key_permissions.create(
        db=db,
        object=KeyPermissionCreate(
            api_key_id=int(created["id"]),
            resource=KeyPermissionResource.FEATURE_FLAGS,
            action=KeyPermissionAction.READ,
        ),
    )
    await db.commit()
    return str(created["api_key"])


async def seed_feature_flags() -> None:
    async with local_session() as db:
        admin = await _admin_user(db)
        created = await _seed_flags(db, admin)
        api_key = await _seed_api_key(db, admin)

    logger.info(f"Feature flags: {created} created, {len(FLAGS) - created} already present")
    if api_key:
        # Written to stdout, not the logger: the plaintext key is only recoverable here, and shipping a live
        # credential into aggregated application logs is worse than making the operator copy it off the terminal.
        print(f"\nDemo evaluation API key for '{ADMIN_USERNAME}' (shown once, not logged):\n  {api_key}")
        print(
            "Try it: curl -H 'X-API-Key: <key>' "
            "'http://localhost:8000/api/v1/flags/evaluate?key=payouts.instant&subject=merchant-42'\n"
        )
    else:
        logger.info(f"API key '{API_KEY_NAME}' already exists; delete it in /admin to mint a new one")


async def main() -> None:
    try:
        await seed_feature_flags()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
