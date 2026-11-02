from rest_framework.permissions import BasePermission


def is_admin(user):
    return bool(user and user.is_authenticated and (user.role == 'admin' or user.is_superuser))


def is_instructor(user):
    return bool(user and user.is_authenticated and (user.role in ('instructor', 'admin') or user.is_superuser))


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return is_admin(request.user)


class IsInstructorOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_instructor(request.user)


def can_manage_course(user, course):
    """Course owner or admin."""
    return bool(user and user.is_authenticated and (is_admin(user) or course.instructor_id == user.id))


def require_verified(user):
    """Raise 403 unless the user has confirmed their email address."""
    from rest_framework.exceptions import PermissionDenied
    if not user.email_verified:
        raise PermissionDenied('Please verify your email address first. Check your inbox or request a new link.',
                               code='email_not_verified')
