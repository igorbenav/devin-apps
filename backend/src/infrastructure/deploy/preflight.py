"""Is this deployment ready to serve traffic?

The app already refuses to start on an insecure production config, but by then the old version is gone. Preflight
answers the same questions from the outside — before the rollout — and adds the two the validator cannot see: whether
the database is reachable at the revision this code expects, and whether Redis (sessions, CSRF, login lockout) is there
at all.
"""

from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import redis.asyncio as redis
from alembic.script import ScriptDirectory
from sqlalchemy import text

from ..config.settings import EnvironmentOption, Settings
from ..database.session import build_engine
from ..security.production_validator import ProductionSecurityValidator

#: ``backend/`` locally, ``/app`` in the image; both hold ``migrations/`` next to the code.
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


@dataclass(frozen=True)
class Problem:
    """One reason not to roll this deployment out."""

    check: str
    detail: str

    def __str__(self) -> str:
        return f"{self.check}: {self.detail}"


def expected_revision() -> str | None:
    """The migration head this checkout ships, or None if the migrations are not next to the code."""
    if not MIGRATIONS_DIR.is_dir():
        return None

    return ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()


def config_problems(settings: Settings) -> list[Problem]:
    """Configuration that would be rejected in production, checked whatever ``ENVIRONMENT`` says."""
    problems = [Problem("config", issue) for issue in ProductionSecurityValidator(settings).critical_issues()]

    if settings.ENVIRONMENT != EnvironmentOption.PRODUCTION:
        problems.append(
            Problem(
                "config",
                f"ENVIRONMENT is '{settings.ENVIRONMENT.value}', so the startup security validation this deployment "
                "relies on will not run. Set ENVIRONMENT=production.",
            )
        )

    if settings.CREATE_TABLES_ON_STARTUP:
        problems.append(
            Problem(
                "config",
                "CREATE_TABLES_ON_STARTUP is true. Alembic owns the schema here; creating tables from the models on "
                "startup diverges from the migration history. Set it to false.",
            )
        )

    return problems


async def database_problems(settings: Settings) -> list[Problem]:
    """Database reachable, and migrated to the revision this code expects."""
    head = expected_revision()
    engine = build_engine(pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            applied = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
    except Exception as exc:  # any driver error here is the same operational answer: do not roll out
        return [Problem("database", f"Could not read the migration revision: {type(exc).__name__}")]
    finally:
        await engine.dispose()

    if applied is None:
        return [Problem("database", "No Alembic revision is applied. Run `alembic upgrade head` before starting.")]
    if head is not None and applied != head:
        return [Problem("database", f"Database is at revision {applied}, this code expects {head}.")]

    return []


async def redis_problems(settings: Settings) -> list[Problem]:
    """Sessions, CSRF tokens and login lockout all live in Redis; without it nobody can log in."""
    client = redis.from_url(settings.SESSION_REDIS_URL)
    try:
        await cast(Awaitable[bool], client.ping())
    except Exception as exc:
        return [Problem("redis", f"Session Redis did not answer a ping: {type(exc).__name__}")]
    finally:
        await client.aclose()

    return []


async def run_checks(settings: Settings) -> list[Problem]:
    """Every preflight problem, in the order a reader should fix them."""
    return config_problems(settings) + await database_problems(settings) + await redis_problems(settings)
