"""The Tool Requests manifest: everything this tool contributes to the platform.

The platform reads this — routers, admin views, permissions, seed — so no
shared registry file needs editing when a tool is added or removed.
"""

from ....platform_sdk import ToolSpec, register
from .admin import ToolRequestAdmin
from .permissions import PERMISSIONS, REQUIRED_PERMISSION
from .router import router
from .seed import seed_demo_data

SPEC = register(
    ToolSpec(
        name="Tool Requests",
        slug="intake",
        description="Describe a tool you need; a Devin session builds it and a human merges it.",
        route_prefix="/tools/intake",
        required_permission=REQUIRED_PERMISSION,
        nav_label="Request a tool",
        pages=router,
        admin_views=(ToolRequestAdmin,),
        permissions=PERMISSIONS,
        seed=seed_demo_data,
    )
)
