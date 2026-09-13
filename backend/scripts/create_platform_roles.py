"""Seed the platform roles and one demo user per role.

Idempotent: re-running updates the role permission lists and leaves existing
users alone. The demo users exist so the prototype can be shown end to end;
their passwords come from ``DEMO_USER_PASSWORD`` (default below) and they should
not exist outside a demo or development database.
"""

import asyncio
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.infrastructure.database.initialize import close_database  # noqa: E402
from src.infrastructure.database.session import local_session  # noqa: E402
from src.infrastructure.logging import get_logger  # noqa: E402
from src.modules.common.exceptions import UserExistsError  # noqa: E402
from src.modules.platform import service as platform_service  # noqa: E402
from src.modules.platform.constants import ROLE_ADMIN, ROLE_ANALYST, ROLE_REVIEWER, SEEDED_ROLES  # noqa: E402
from src.modules.user.schemas import UserCreate  # noqa: E402
from src.modules.user.service import UserService  # noqa: E402

logger = get_logger()

DEMO_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "Demo1234!")

DEMO_USERS: list[tuple[str, str, str, str]] = [
    ("Ana Analyst", "analyst", "analyst@example.com", ROLE_ANALYST),
    ("Rex Reviewer", "reviewer", "reviewer@example.com", ROLE_REVIEWER),
    ("Ada Admin", "toolsadmin", "toolsadmin@example.com", ROLE_ADMIN),
]


async def create_platform_roles() -> None:
    """Create/update the three roles and their demo users, then print credentials."""
    user_service = UserService()

    async with local_session() as db:
        for name, (description, permissions) in SEEDED_ROLES.items():
            await platform_service.upsert_role(db, None, name, description, list(permissions))
            logger.info(f"Role '{name}' seeded with {len(permissions)} permissions")

        for full_name, username, email, role_name in DEMO_USERS:
            try:
                user = await user_service.create(
                    UserCreate(name=full_name, username=username, email=email, password=DEMO_PASSWORD),
                    db,
                )
                logger.info(f"Created demo user '{username}'")
            except UserExistsError:
                user = await user_service.get_by_username(username, db)
                logger.info(f"Demo user '{username}' already exists")

            await platform_service.assign_role(db, None, int(user["id"]), role_name)

    print("\nSeeded platform roles and demo users:")
    for full_name, username, email, role_name in DEMO_USERS:
        print(f"  {role_name:<9} username={username:<11} email={email:<26} password={DEMO_PASSWORD}")
    print("\nThese demo users are for development and demos only. Do not seed them in production.\n")


async def main() -> None:
    try:
        await create_platform_roles()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
