"""SQLAdmin view for the Refunds tool.

Read-only: refunds move between states in the service layer, where the rules live and the audit
trail is written. Editing one here would bypass both.
"""

from sqladmin import ModelView

from ....platform_sdk import PERM_PLATFORM_ADMIN, PermissionGatedView
from .models import RefundRequest


class RefundRequestAdmin(PermissionGatedView, ModelView, model=RefundRequest):
    """Back-office view of refund requests."""

    required_permission = PERM_PLATFORM_ADMIN

    name = "Refund Request"
    name_plural = "Refund Requests"
    icon = "fa-solid fa-money-bill-transfer"
    category = "Internal Tools"

    column_list = [
        RefundRequest.id,
        RefundRequest.customer_ref,
        RefundRequest.order_ref,
        RefundRequest.amount,
        RefundRequest.currency,
        RefundRequest.state,
        RefundRequest.requested_by,
        RefundRequest.decided_by,
        RefundRequest.processed_by,
    ]
    column_searchable_list = [RefundRequest.customer_ref, RefundRequest.order_ref]
    column_sortable_list = [RefundRequest.id, RefundRequest.amount, RefundRequest.state, RefundRequest.created_at]

    can_create = False
    can_edit = False
    can_delete = False
    can_view_details = True
