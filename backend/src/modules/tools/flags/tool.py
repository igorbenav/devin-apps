"""ToolSpec for Feature Flags — imported by the platform registry at startup."""

from ...platform.registry import ToolSpec, register

SPEC = register(
    ToolSpec(
        name="Feature Flags",
        slug="flags",
        description="Read and flip feature flags.",
        route_prefix="/tools/flags",
        required_permission="flags.read",
        nav_label="Feature Flags",
    )
)
