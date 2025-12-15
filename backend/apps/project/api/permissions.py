from rest_framework import permissions


class ProjectAccessPermission(permissions.BasePermission):
    """
    Read: any user with view rights.
    Write: restricted to editors/owners/staff.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return obj.can_view(request.user)
        return obj.can_edit(request.user)

