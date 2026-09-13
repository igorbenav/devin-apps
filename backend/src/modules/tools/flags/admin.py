"""SQLAdmin view for the Feature Flags tool.

The tool page is deliberately minimal (toggle and create); anything beyond that — editing descriptions, rollout
percentages, deleting a retired flag — happens here.
"""

from sqladmin import ModelView

from ...platform.admin import PermissionGatedView
from ...platform.constants import PERM_PLATFORM_ADMIN
from .models import Flag


class FlagAdmin(PermissionGatedView, ModelView, model=Flag):
    """Back-office view of the feature flags."""

    required_permission = PERM_PLATFORM_ADMIN

    name = "Feature Flag"
    name_plural = "Feature Flags"
    icon = "fa-solid fa-toggle-on"
    category = "Internal Tools"

    column_list = [Flag.id, Flag.key, Flag.enabled, Flag.rollout_percent, Flag.updated_at]
    column_searchable_list = [Flag.key]
    column_sortable_list = [Flag.key, Flag.enabled, Flag.rollout_percent]

    can_create = False
    can_edit = True
    can_delete = True
    can_view_details = True
