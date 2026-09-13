"""Run the demo seed of every registered tool.

One script for all tools: each tool declares its ``seed`` in ``tool.py`` and
the registry calls it, so adding a tool never adds a script here.
"""

import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.infrastructure.database.initialize import close_database  # noqa: E402
from src.infrastructure.database.session import local_session  # noqa: E402
from src.infrastructure.logging import get_logger  # noqa: E402
from src.modules.platform.registry import run_tool_seeds  # noqa: E402

logger = get_logger()


async def seed_tools() -> None:
    """Seed demo data for every tool that declares a seed."""
    async with local_session() as db:
        seeded = await run_tool_seeds(db)

    logger.info(f"Seeded tools: {', '.join(seeded) if seeded else 'none'}")


async def main() -> None:
    try:
        await seed_tools()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
