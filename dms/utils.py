from .models import Department, DocumentAccess
from django.db.models import Q


def get_allowed_departments(user):
    """
    Возвращает queryset Department, которые пользователь может видеть.
    ADMIN — все отделы.
    Остальные — свой отдел + все нижестоящие.
    """
    if user.role == "ADMIN":
        return Department.objects.all()

    if not user.department_id:
        return Department.objects.none()

    root = Department.objects.get(id=user.department_id)
    return root.get_descendants(include_self=True)

def get_allowed_documents(user):
    from dms.models import Document

    if user.role == "ADMIN":
        return Document.objects.all()

    if not user.department_id:
        return Document.objects.none()

    allowed_depts = get_allowed_departments(user)

    return (
        Document.objects
        .filter(
            Q(department__in=allowed_depts) |
            Q(accesses__department=user.department)
        )
        .distinct()
    )


def user_can_access_document(user, doc):
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

