"""Everything this tool contributes to the platform, in one manifest.

The platform imports this module at startup and collects the pages, admin views, permissions and seed from the spec.
Nothing outside this directory mentions KYC.
"""

from ....platform_sdk import ToolSpec, register
from .admin import KycCaseAdmin, KycDocumentAdmin
from .permissions import PERM_KYC_REVIEW, PERMISSIONS
from .router import router
from .seed import seed_demo_data

SPEC = register(
    ToolSpec(
        name="KYC Review Queue",
        slug="kyc",
        description="Review, claim and decide pending KYC cases.",
        route_prefix="/tools/kyc",
        required_permission=PERM_KYC_REVIEW,
        nav_label="KYC Review Queue",
        pages=router,
        admin_views=(KycCaseAdmin, KycDocumentAdmin),
        permissions=PERMISSIONS,
        seed=seed_demo_data,
    )
)
