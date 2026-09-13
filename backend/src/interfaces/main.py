from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from ..infrastructure.app_factory import create_application, lifespan_factory
from ..infrastructure.config.settings import get_settings
from ..infrastructure.security import validate_production_security
from ..interfaces.api import router
from ..modules.platform.setup import setup_platform
from .admin.initialize import create_admin_interface

settings = get_settings()


@asynccontextmanager
async def lifespan_with_security(app: FastAPI) -> AsyncGenerator[None, None]:
    """Custom lifespan that includes security validation."""
    if settings.PRODUCTION_SECURITY_VALIDATION_ENABLED:
        validate_production_security(settings)

    default_lifespan = lifespan_factory(
        settings,
        create_tables_on_startup=settings.CREATE_TABLES_ON_STARTUP,
    )

    async with default_lifespan(app):
        yield


app = create_application(
    router=router,
    settings=settings,
    lifespan=lifespan_with_security,
    create_tables_on_startup=None,
    enable_cors=None,
    cors_origins=None,
    enable_docs_in_production=None,
    docs_production_dependency=None,
    enable_gzip=None,
    openapi_prefix=None,
    title="FastAPI Boilerplate",
    summary="A modular FastAPI starter with a plugin system",
    description="""
    # FastAPI Boilerplate

    A modern FastAPI starter with:

    * Vertical-slice modules and a clean infrastructure layer
    * Session-based auth with OAuth providers
    * Swappable cache, queue, and rate-limit backends
    * SQLAdmin admin UI
    """,
    version="0.19.0",
    contact={
        "name": "Benav Labs",
        "url": "https://github.com/benavlabs/FastAPI-boilerplate",
        "email": "contact@benav.io",
    },
    license_info={
        "name": "MIT",
        "identifier": "MIT",
    },
    openapi_tags=None,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# SQLAdmin's login state rides this signed cookie; Starlette's defaults are a 14-day lifetime over plain HTTP, so it
# follows the same rules as the crudauth session cookie instead.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="admin_session",
    https_only=settings.SESSION_SECURE_COOKIES,
    same_site="lax",
    max_age=settings.SESSION_TIMEOUT_MINUTES * 60,
)
setup_platform(app)
create_admin_interface(app)


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """Health check endpoint for monitoring and load balancers."""
    return {"status": "healthy"}
