"""Create or update the platform roles: `python -m scripts.sync_roles`.

Production-safe half of ``create_platform_roles``: roles and their permission lists, no demo users and no demo data.
Run it on every deploy — a new tool contributes new permission strings through its manifest, and the roles that should
hold them only change when this runs.
"""

import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.infrastructure.database.initialize import close_database  # noqa: E402
from src.infrastructure.database.session import local_session  # noqa: E402
from src.infrastructure.logging import get_logger  # noqa: E402
from src.modules.platform import service as platform_service  # noqa: E402
from src.modules.platform.constants import seeded_roles  # noqa: E402
from src.modules.platform.registry import discover_tools  # noqa: E402

logger = get_logger()


async def sync_roles() -> None:
    """Upsert every seeded role with the permission catalog the installed tools currently declare."""
    discover_tools()  # a tool's permissions come from its manifest, so the tools have to be imported first

    async with local_session() as db:
        for name, (description, permissions) in seeded_roles().items():
            await platform_service.upsert_role(db, None, name, description, list(permissions))
            logger.info(f"Role '{name}' synced with {len(permissions)} permissions")


async def main() -> None:
    try:
        await sync_roles()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
