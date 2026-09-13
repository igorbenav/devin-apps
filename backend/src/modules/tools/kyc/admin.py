"""SQLAdmin views for the KYC Review Queue tool.

Read-only: cases move through their states in the service layer, where the
rules live and the audit trail is written. Editing a case here would bypass
both, so the back office can look but not touch.
"""

from sqladmin import ModelView

from ...platform.admin import PermissionGatedView
from ...platform.constants import PERM_PLATFORM_ADMIN
from .models import KycCase, KycDocument


class KycCaseAdmin(PermissionGatedView, ModelView, model=KycCase):
    """Back-office view of KYC cases."""

    required_permission = PERM_PLATFORM_ADMIN

    name = "KYC Case"
    name_plural = "KYC Cases"
    icon = "fa-solid fa-id-card"
    category = "Internal Tools"

    column_list = [
        KycCase.id,
        KycCase.customer_ref,
        KycCase.customer_name,
        KycCase.risk_score,
        KycCase.state,
        KycCase.assigned_to,
        KycCase.decided_by,
    ]
    column_searchable_list = [KycCase.customer_ref, KycCase.customer_name]
    column_sortable_list = [KycCase.id, KycCase.risk_score, KycCase.state, KycCase.submitted_at]

    can_create = False
    can_edit = False
    can_delete = False
    can_view_details = True


class KycDocumentAdmin(PermissionGatedView, ModelView, model=KycDocument):
    """Back-office view of the documents attached to a case."""

    required_permission = PERM_PLATFORM_ADMIN

    name = "KYC Document"
    name_plural = "KYC Documents"
    icon = "fa-solid fa-file-lines"
    category = "Internal Tools"

    column_list = [KycDocument.id, KycDocument.case_id, KycDocument.kind, KycDocument.filename, KycDocument.status]
    column_searchable_list = [KycDocument.filename]
    column_sortable_list = [KycDocument.id, KycDocument.case_id]

    can_create = False
    can_edit = False
    can_delete = False
    can_view_details = True
