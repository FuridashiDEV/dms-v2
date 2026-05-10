from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from mptt.admin import MPTTModelAdmin

from .models import Department, DocumentType, Document, DocumentActivity, DocumentRelation, DocumentVersion, Folder, User
from .forms import UserAdminChangeForm


# =========================
# Department (MPTT Tree)
# =========================
@admin.register(Department)
class DepartmentAdmin(MPTTModelAdmin):
    mptt_indent_field = "name"
    list_display = ("name", "parent")
    list_filter = ("parent",)
    search_fields = ("name",)


@admin.register(Folder)
class FolderAdmin(MPTTModelAdmin):
    mptt_indent_field = "name"
    list_display = ("name", "department", "parent")
    list_filter = ("department",)
    search_fields = ("name",)


# =========================
# DocumentType
# =========================
@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    list_display = ("name",)


# =========================
# Document
# =========================
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "public_id",
        "status",
        "department",
        "doc_type",
        "language",
        "retention_until",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("status", "department", "doc_type", "language", "doc_date", "retention_until", "legal_hold")
    search_fields = ("title", "description", "document_author", "public_id", "uploaded_by__username", "checksum_sha256")
    date_hierarchy = "doc_date"
    autocomplete_fields = ("department", "folder", "doc_type", "uploaded_by")


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


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "number",
        "status",
        "department",
        "doc_type",
        "language",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("status", "department", "doc_type", "language", "created_at")
    search_fields = ("document__title", "title", "document_author", "uploaded_by__username", "checksum_sha256")
    autocomplete_fields = ("document", "department", "doc_type", "folder", "uploaded_by")


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
