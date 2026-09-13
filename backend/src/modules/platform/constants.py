"""Permission strings and the seeded role definitions.

Permissions are flat strings (``"<area>.<action>"``). There is no hierarchy and
no implication between them: holding ``kyc.approve`` does not grant
``kyc.review``. Roles are the only place permissions are grouped.
"""

from typing import Final

PERM_KYC_REVIEW: Final = "kyc.review"
PERM_KYC_APPROVE: Final = "kyc.approve"
PERM_KYC_ESCALATE: Final = "kyc.escalate"
PERM_FLAGS_READ: Final = "flags.read"
PERM_FLAGS_WRITE: Final = "flags.write"
PERM_AUDIT_READ: Final = "audit.read"
PERM_PLATFORM_ADMIN: Final = "platform.admin"

ALL_PERMISSIONS: Final[tuple[str, ...]] = (
    PERM_KYC_REVIEW,
    PERM_KYC_APPROVE,
    PERM_KYC_ESCALATE,
    PERM_FLAGS_READ,
    PERM_FLAGS_WRITE,
    PERM_AUDIT_READ,
    PERM_PLATFORM_ADMIN,
)

ROLE_ANALYST: Final = "analyst"
ROLE_REVIEWER: Final = "reviewer"
ROLE_ADMIN: Final = "admin"

ANALYST_PERMISSIONS: Final[tuple[str, ...]] = (PERM_KYC_REVIEW, PERM_FLAGS_READ)
REVIEWER_PERMISSIONS: Final[tuple[str, ...]] = (*ANALYST_PERMISSIONS, PERM_KYC_APPROVE, PERM_KYC_ESCALATE)
ADMIN_PERMISSIONS: Final[tuple[str, ...]] = ALL_PERMISSIONS

SEEDED_ROLES: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    ROLE_ANALYST: ("Reviews KYC cases and reads risk flags", ANALYST_PERMISSIONS),
    ROLE_REVIEWER: ("Approves and escalates KYC cases", REVIEWER_PERMISSIONS),
    ROLE_ADMIN: ("Full platform access, including the audit log", ADMIN_PERMISSIONS),
}

ROLE_NAME_MAX_LENGTH: Final = 50
ACTION_MAX_LENGTH: Final = 100
ENTITY_TYPE_MAX_LENGTH: Final = 100
ENTITY_ID_MAX_LENGTH: Final = 64
REQUEST_ID_MAX_LENGTH: Final = 64
IP_MAX_LENGTH: Final = 45

AUDIT_PAGE_SIZE: Final = 200
