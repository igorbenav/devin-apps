"""The permissions this tool owns.

Declared here, collected into the app-wide catalog through the ``ToolSpec`` in
``tool.py``. Kept in its own module so routes and services can import the
strings without importing ``tool.py``, which imports them.
"""

from typing import Final

from ....platform_sdk import Permission

SLUG: Final = "intake"

REQUIRED_PERMISSION: Final = "tools.request"
PERM_REQUEST_ADMIN: Final = "tools.request.admin"

PERMISSIONS: Final[tuple[Permission, ...]] = (
    Permission(REQUIRED_PERMISSION, "Submit a tool request and see your own requests"),
    Permission(PERM_REQUEST_ADMIN, "See every requester's tool requests and retry a failed dispatch"),
)
