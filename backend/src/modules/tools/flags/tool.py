"""Everything this tool contributes to the platform, in one manifest.

The platform imports this module at startup and collects the pages, JSON API,
admin view, permissions and seed from the spec. Nothing outside this directory
mentions feature flags — including ``interfaces/api/v1``, which mounts ``api``
under ``/api/v1/flags`` through the registry.
"""

from ....platform_sdk import ToolSpec, register
from .admin import FlagAdmin
from .api import router as api_router
from .permissions import PERM_FLAGS_READ, PERMISSIONS
from .router import router
from .seed import seed_demo_data

SPEC = register(
    ToolSpec(
        name="Feature Flags",
        slug="flags",
        description="Read and flip feature flags.",
        route_prefix="/tools/flags",
        required_permission=PERM_FLAGS_READ,
        nav_label="Feature Flags",
        pages=router,
        api=api_router,
        api_prefix="/flags",
        admin_views=(FlagAdmin,),
        permissions=PERMISSIONS,
        seed=seed_demo_data,
    )
)
