"""The permissions this tool owns.

Declared here, collected into the app-wide catalog through the ``ToolSpec`` in
``tool.py``. Kept in its own module so routes and services can import the
strings without importing ``tool.py``, which imports them.

Which seeded role holds each of these is a shared decision in the platform's
``ROLE_GRANTS``: agents hold view/request/process, the team lead additionally
holds approve.
"""

from typing import Final

from ....platform_sdk import Permission

SLUG: Final = "refunds"

REQUIRED_PERMISSION: Final = "refunds.view"
PERM_REFUNDS_REQUEST: Final = "refunds.request"
PERM_REFUNDS_APPROVE: Final = "refunds.approve"
PERM_REFUNDS_PROCESS: Final = "refunds.process"

PERMISSIONS: Final[tuple[Permission, ...]] = (
    Permission(REQUIRED_PERMISSION, "See the refund dashboard and any refund's audit trail"),
    Permission(PERM_REFUNDS_REQUEST, "Raise a refund request"),
    Permission(PERM_REFUNDS_APPROVE, "Approve or reject a refund someone else requested"),
    Permission(PERM_REFUNDS_PROCESS, "Mark an approved refund as paid out"),
)
