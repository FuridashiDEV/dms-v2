from __future__ import annotations

from dataclasses import dataclass

from django.core.files.uploadedfile import SimpleUploadedFile

from dms.models import Counterparty, Department, Document, Organization, User


@dataclass
class OrgContext:
    organization: Organization
    department: Department
    user: User


def make_org_context(
    *,
    slug: str,
    org_name: str | None = None,
    department_name: str = "QA Department",
    username: str | None = None,
    role: str = User.Role.EMPLOYEE,
) -> OrgContext:
    organization = Organization.objects.create(
        name=org_name or slug.replace("-", " ").title(),
        slug=slug,
    )
    department = Department.objects.create(
        organization=organization,
        name=department_name,
    )
    user = User.objects.create_user(
        username=username or f"{slug}-user",
        password="password123",
        role=role,
        department=department,
    )
    return OrgContext(organization=organization, department=department, user=user)


def make_document(
    *,
    context: OrgContext,
    title: str = "QA document",
    filename: str = "qa-document.txt",
    content: bytes = b"qa payload",
    create_version: bool = True,
) -> Document:
    document = Document.objects.create(
        organization=context.organization,
        department=context.department,
        title=title,
        file=SimpleUploadedFile(filename, content, content_type="text/plain"),
        uploaded_by=context.user,
    )
    if create_version:
        document.create_version(uploaded_by=context.user)
    return document


def make_counterparty(
    *,
    context: OrgContext,
    name: str = "QA Counterparty LLP",
    email: str = "qa-counterparty@example.test",
) -> Counterparty:
    return Counterparty.objects.create(
        organization=context.organization,
        name=name,
        email=email,
        created_by=context.user,
    )
