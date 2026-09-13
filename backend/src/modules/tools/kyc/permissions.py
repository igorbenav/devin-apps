"""The permissions this tool owns.

Declared here, collected into the app-wide catalog through the ``ToolSpec``.
Kept in its own module so routes and services can import the strings without
importing ``tool.py``, which imports them.
"""

from typing import Final

from ....platform_sdk import Permission

SLUG: Final = "kyc"

PERM_KYC_REVIEW: Final = "kyc.review"
PERM_KYC_APPROVE: Final = "kyc.approve"
PERM_KYC_ESCALATE: Final = "kyc.escalate"

PERMISSIONS: Final[tuple[Permission, ...]] = (
    Permission(PERM_KYC_REVIEW, "See the queue, open a case and claim it"),
    Permission(PERM_KYC_APPROVE, "Approve or reject a case someone else claimed"),
    Permission(PERM_KYC_ESCALATE, "Escalate a case to compliance"),
)
