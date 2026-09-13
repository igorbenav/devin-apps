"""The permissions this tool owns.

Declared here, collected into the app-wide catalog through the ``ToolSpec``.
Kept in its own module so routes and services can import the strings without
importing ``tool.py``, which imports them.
"""

from typing import Final

from ....platform_sdk import Permission

SLUG: Final = "flags"

PERM_FLAGS_READ: Final = "flags.read"
PERM_FLAGS_WRITE: Final = "flags.write"

PERMISSIONS: Final[tuple[Permission, ...]] = (
    Permission(PERM_FLAGS_READ, "See the flag table and its current values"),
    Permission(PERM_FLAGS_WRITE, "Create a flag and flip one on or off"),
)
