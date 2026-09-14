"""The Refunds manifest: everything this tool contributes to the platform.

The platform reads this — routes, admin view, permissions, seed — so no shared registry file
needs editing when a tool is added or removed. The one shared decision is which seeded role
holds the permissions declared here, which lives in the platform's ``ROLE_GRANTS``.
"""

from ....platform_sdk import ToolSpec, register
from .admin import RefundRequestAdmin
from .permissions import PERMISSIONS, REQUIRED_PERMISSION
from .router import router
from .seed import seed_demo_data

SPEC = register(
    ToolSpec(
        name="Refunds",
        slug="refunds",
        description="Review, approve and process customer refund requests.",
        route_prefix="/tools/refunds",
        required_permission=REQUIRED_PERMISSION,
        nav_label="Refunds",
        pages=router,
        admin_views=(RefundRequestAdmin,),
        permissions=PERMISSIONS,
        seed=seed_demo_data,
    )
)
