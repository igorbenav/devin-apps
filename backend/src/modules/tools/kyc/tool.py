"""ToolSpec for KYC Review Queue — imported by the platform registry at startup."""

from ...platform.registry import ToolSpec, register

SPEC = register(
    ToolSpec(
        name="KYC Review Queue",
        slug="kyc",
        description="Review, claim and decide pending KYC cases.",
        route_prefix="/tools/kyc",
        required_permission="kyc.review",
        nav_label="KYC Review Queue",
    )
)
