from django.db.models import Q

from .models import Department, DocumentAccess, Organization, OrganizationMember


def get_user_organizations(user):
    if not getattr(user, "is_authenticated", False):
        return Organization.objects.none()

    memberships = OrganizationMember.objects.filter(
        user=user,
        is_active=True,
        organization__is_active=True,
    ).values_list("organization_id", flat=True)
    organization_ids = list(memberships)
    if organization_ids:
        return Organization.objects.filter(id__in=organization_ids, is_active=True)

    if getattr(user, "department_id", None):
        return Organization.objects.filter(
            id=user.department.organization_id,
            is_active=True,
        )

    if getattr(user, "role", None) == "ADMIN":
        return Organization.objects.filter(slug="default", is_active=True)

    return Organization.objects.none()


def get_primary_organization(user):
    return get_user_organizations(user).order_by("name", "id").first()


def get_allowed_departments(user):
    """
    Возвращает queryset Department, которые пользователь может видеть.
    ADMIN — все отделы внутри доступных организаций.
    Остальные — свой отдел + все нижестоящие внутри организации пользователя.
    """
    organizations = get_user_organizations(user)
    if not organizations.exists():
        return Department.objects.none()

    if user.role == "ADMIN":
        return Department.objects.filter(organization__in=organizations)

    if not user.department_id:
        return Department.objects.none()

    root = Department.objects.get(id=user.department_id)
    if not organizations.filter(id=root.organization_id).exists():
        return Department.objects.none()

    return root.get_descendants(include_self=True).filter(
        organization=root.organization,
    )


def get_allowed_documents(user):
    from dms.models import Document

    organizations = get_user_organizations(user)
    if not organizations.exists():
        return Document.objects.none()

    base_qs = Document.objects.filter(organization__in=organizations)

    if user.role == "ADMIN":
        return base_qs

    if not user.department_id:
        return Document.objects.none()

    allowed_depts = get_allowed_departments(user)

    return (
        base_qs
        .filter(
            Q(department__in=allowed_depts) |
            Q(accesses__department=user.department)
        )
        .distinct()
    )


def user_can_access_document(user, doc):
    if not get_user_organizations(user).filter(id=doc.organization_id).exists():
        return False

    if user.role == "ADMIN":
        return True

    if not user.department_id:
        return False

    if get_allowed_departments(user).filter(id=doc.department_id).exists():
        return True

    return DocumentAccess.objects.filter(
        document=doc,
        department=user.department,
    ).exists()

