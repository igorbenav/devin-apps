"""The platform's own permissions, the seeded roles, and shared column limits.

Permissions are flat strings (``"<area>.<action>"``). There is no hierarchy and
no implication between them: holding ``kyc.approve`` does not grant
``kyc.review``. Roles are the only place permissions are grouped.

Only the two permissions the *platform* owns live here. A tool declares its own
in its ``ToolSpec`` and :func:`permission_catalog` collects them, so adding a
tool does not mean editing this file. Which seeded role receives a new
permission is a human decision and stays in :data:`ROLE_GRANTS` — that is the
one shared edit adding a tool still needs.
"""

from typing import Final

from .registry import Permission, tool_permissions

PERM_AUDIT_READ: Final = "audit.read"
PERM_PLATFORM_ADMIN: Final = "platform.admin"

PLATFORM_PERMISSIONS: Final[tuple[Permission, ...]] = (
    Permission(PERM_AUDIT_READ, "Read the audit log at /audit"),
    Permission(PERM_PLATFORM_ADMIN, "Reach the SQLAdmin back office"),
)

ROLE_ANALYST: Final = "analyst"
ROLE_REVIEWER: Final = "reviewer"
ROLE_ADMIN: Final = "admin"

ANALYST_GRANTS: Final[tuple[str, ...]] = ("kyc.review", "flags.read")
REVIEWER_GRANTS: Final[tuple[str, ...]] = (*ANALYST_GRANTS, "kyc.approve", "kyc.escalate")

ROLE_GRANTS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    ROLE_ANALYST: ("Reviews KYC cases and reads risk flags", ANALYST_GRANTS),
    ROLE_REVIEWER: ("Approves and escalates KYC cases", REVIEWER_GRANTS),
    ROLE_ADMIN: ("Full platform access, including the audit log", ()),
}

ROLE_NAME_MAX_LENGTH: Final = 50
ACTION_MAX_LENGTH: Final = 100
ENTITY_TYPE_MAX_LENGTH: Final = 100
ENTITY_ID_MAX_LENGTH: Final = 64
REQUEST_ID_MAX_LENGTH: Final = 64
IP_MAX_LENGTH: Final = 45

AUDIT_PAGE_SIZE: Final = 200


def permission_catalog() -> tuple[Permission, ...]:
    """Every permission in the app: the platform's, plus every registered tool's."""
    return (*PLATFORM_PERMISSIONS, *tool_permissions())


def permission_names() -> tuple[str, ...]:
    """The catalog as plain strings."""
    return tuple(permission.name for permission in permission_catalog())


def seeded_roles() -> dict[str, tuple[str, tuple[str, ...]]]:
    """The demo roles, with ``admin`` resolved to whatever the catalog currently holds.

    Raises ``ValueError`` if a role grants a permission no tool declares — the
    typo that would otherwise silently give a role nothing.
    """
    catalog = set(permission_names())
    roles = {}
    for name, (description, grants) in ROLE_GRANTS.items():
        resolved = tuple(sorted(catalog)) if name == ROLE_ADMIN else grants
        unknown = sorted(set(resolved) - catalog)
        if unknown:
            raise ValueError(f"Role '{name}' grants unknown permissions: {', '.join(unknown)}")
        roles[name] = (description, resolved)
    return roles
