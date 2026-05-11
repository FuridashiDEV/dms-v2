from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from mptt.admin import MPTTModelAdmin

from .models import (
    AuditEvent,
    Department,
    Document,
    DocumentActivity,
    DocumentRelation,
    DocumentType,
    DocumentVersion,
    Folder,
    ExtractedField,
    ImportBatch,
    ImportFile,
    Organization,
    OrganizationMember,
    ProcessingJob,
    User,
)
from .forms import UserAdminChangeForm


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "is_active", "created_at")
    list_filter = ("organization", "role", "is_active")
    search_fields = ("organization__name", "user__username", "user__email")
    autocomplete_fields = ("organization", "user")


# =========================
# Department (MPTT Tree)
# =========================
@admin.register(Department)
class DepartmentAdmin(MPTTModelAdmin):
    mptt_indent_field = "name"
    list_display = ("name", "organization", "parent")
    list_filter = ("organization", "parent")
    search_fields = ("name",)
    autocomplete_fields = ("organization",)


@admin.register(Folder)
class FolderAdmin(MPTTModelAdmin):
    mptt_indent_field = "name"
    list_display = ("name", "organization", "department", "parent")
    list_filter = ("organization", "department")
    search_fields = ("name",)
    autocomplete_fields = ("organization", "department", "parent")


# =========================
# DocumentType
# =========================
@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    list_display = ("name", "organization")
    list_filter = ("organization",)
    autocomplete_fields = ("organization",)


# =========================
# Document
# =========================
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "public_id",
        "status",
        "organization",
        "department",
        "doc_type",
        "language",
        "retention_until",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("status", "organization", "department", "doc_type", "language", "doc_date", "retention_until", "legal_hold")
    search_fields = ("title", "description", "document_author", "public_id", "uploaded_by__username", "checksum_sha256")
    date_hierarchy = "doc_date"
    autocomplete_fields = ("organization", "department", "folder", "doc_type", "uploaded_by")


# =========================
# DocumentActivity
# =========================
@admin.register(DocumentActivity)
class DocumentActivityAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "document")
    list_filter = ("action", "created_at")
    search_fields = ("user__username", "document__title")
    date_hierarchy = "created_at"
    autocomplete_fields = ("user", "document")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "event_type",
        "organization",
        "user",
        "document",
        "document_version",
        "ip_address",
    )
    list_filter = ("event_type", "organization", "created_at")
    search_fields = (
        "document__title",
        "user__username",
        "ip_address",
        "user_agent",
    )
    readonly_fields = (
        "created_at",
        "event_type",
        "organization",
        "user",
        "document",
        "document_version",
        "ip_address",
        "user_agent",
        "metadata",
    )
    autocomplete_fields = ("organization", "user", "document", "document_version")

    def has_add_permission(self, request):
        return False


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "number",
        "status",
        "organization",
        "department",
        "doc_type",
        "language",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("status", "organization", "department", "doc_type", "language", "created_at")
    search_fields = ("document__title", "title", "document_author", "uploaded_by__username", "checksum_sha256")
    autocomplete_fields = ("document", "organization", "department", "doc_type", "folder", "uploaded_by")


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "document",
        "organization",
        "status",
        "source",
        "created_by",
        "completed_at",
    )
    list_filter = ("status", "source", "organization", "created_at")
    search_fields = ("document__title", "created_by__username", "error_message")
    readonly_fields = ("raw_result", "error_message", "created_at", "started_at", "completed_at")
    autocomplete_fields = ("organization", "document", "created_by")


@admin.register(ExtractedField)
class ExtractedFieldAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "document",
        "field_name",
        "status",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = ("status", "field_name", "organization", "created_at")
    search_fields = ("document__title", "field_name", "value", "reviewed_by__username")
    autocomplete_fields = ("organization", "job", "document", "reviewed_by")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "organization",
        "department",
        "folder",
        "created_by",
        "status",
        "total_files",
        "imported_files",
        "duplicate_files",
        "failed_files",
    )
    list_filter = ("status", "organization", "created_at")
    search_fields = ("created_by__username", "department__name", "folder__name")
    autocomplete_fields = ("organization", "department", "folder", "created_by")
    readonly_fields = ("created_at", "completed_at")


@admin.register(ImportFile)
class ImportFileAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "batch",
        "original_file_name",
        "status",
        "document",
        "duplicate_of",
        "checksum_sha256",
    )
    list_filter = ("status", "organization", "created_at")
    search_fields = ("original_file_name", "checksum_sha256", "document__title")
    autocomplete_fields = ("batch", "organization", "document", "duplicate_of")
    readonly_fields = ("created_at",)


@admin.register(DocumentRelation)
class DocumentRelationAdmin(admin.ModelAdmin):
    list_display = ("from_document", "relation_type", "to_document", "confidence", "created_at")
    list_filter = ("relation_type", "created_at")
    search_fields = ("from_document__title", "to_document__title")
    autocomplete_fields = ("from_document", "to_document")


# =========================
# User
# =========================
@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserAdminChangeForm
    model = User

    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "department",
        "position",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "department", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name", "position")
    ordering = ("username",)

    autocomplete_fields = ("department",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Персональные данные", {"fields": ("first_name", "last_name", "email")}),
        ("DMS", {"fields": ("role", "department", "position")}),
        (
            "Права доступа",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Новый пароль", {"fields": ("new_password",)}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "role",
                    "department",
                    "position",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )
