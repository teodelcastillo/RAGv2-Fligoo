from rest_framework import permissions


class EvaluationAccessPermission(permissions.BasePermission):
    """
    Read access for viewers; write operations require editor/owner/staff.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return obj.can_view(request.user)
        return obj.can_edit(request.user)

