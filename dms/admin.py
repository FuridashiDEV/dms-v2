from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from mptt.admin import MPTTModelAdmin

from .models import (
    AuditEvent,
    Counterparty,
    CounterpartyContact,
    Department,
    Document,
    DocumentActivity,
    DocumentExchange,
    DocumentRelation,
    DocumentType,
    DocumentVersion,
    ExchangeEvent,
    ExchangeMessage,
    Folder,
    ExtractedField,
    ImportBatch,
    ImportFile,
    ExternalReference,
    IntegrationConnection,
    IntegrationProvider,
    IntegrationSyncJob,
    Notification,
    Organization,
    OrganizationMember,
    Plan,
    PlanQuota,
    ProcessingJob,
    Subscription,
    UsageEvent,
    User,
    WebhookDelivery,
    WebhookEndpoint,
    WorkflowAction,
    WorkflowInstance,
    WorkflowStepTemplate,
    WorkflowTemplate,
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


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "notification_type", "recipient", "organization", "is_read", "related_document", "related_exchange")
    list_filter = ("notification_type", "is_read", "organization", "created_at")
    search_fields = ("recipient__username", "title", "message", "related_document__title")
    readonly_fields = ("created_at", "read_at")
    autocomplete_fields = ("organization", "recipient", "actor", "related_document", "related_exchange")


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


class WorkflowStepTemplateInline(admin.TabularInline):
    model = WorkflowStepTemplate
    extra = 1
    autocomplete_fields = ("approver_user", "approver_department")


@admin.register(WorkflowTemplate)
class WorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_active", "created_by", "created_at")
    list_filter = ("is_active", "organization", "created_at")
    search_fields = ("name", "description", "created_by__username")
    autocomplete_fields = ("organization", "created_by")
    inlines = (WorkflowStepTemplateInline,)


@admin.register(WorkflowStepTemplate)
class WorkflowStepTemplateAdmin(admin.ModelAdmin):
    list_display = ("template", "order", "name", "approver_user", "approver_department")
    list_filter = ("template__organization",)
    search_fields = ("template__name", "name", "approver_user__username", "approver_department__name")
    autocomplete_fields = ("template", "approver_user", "approver_department")


@admin.register(WorkflowInstance)
class WorkflowInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "document",
        "template",
        "status",
        "current_step_template",
        "started_by",
        "completed_at",
    )
    list_filter = ("status", "organization", "started_at")
    search_fields = ("document__title", "template__name", "started_by__username")
    autocomplete_fields = (
        "organization",
        "document",
        "template",
        "current_step_template",
        "started_by",
    )
    readonly_fields = ("started_at", "completed_at")


@admin.register(WorkflowAction)
class WorkflowActionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "instance",
        "document",
        "step_template",
        "actor",
        "action_type",
    )
    list_filter = ("action_type", "organization", "created_at")
    search_fields = ("document__title", "actor__username", "comment")
    autocomplete_fields = ("organization", "instance", "document", "step_template", "actor")
    readonly_fields = ("created_at",)


@admin.register(Counterparty)
class CounterpartyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "email", "contact_name", "is_active", "created_by", "created_at")
    list_filter = ("is_active", "organization", "created_at")
    search_fields = ("name", "email", "contact_name", "created_by__username")
    autocomplete_fields = ("organization", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(CounterpartyContact)
class CounterpartyContactAdmin(admin.ModelAdmin):
    list_display = ("name", "counterparty", "email", "position", "phone", "is_active", "created_by", "created_at")
    list_filter = ("is_active", "counterparty__organization", "created_at")
    search_fields = ("name", "email", "position", "phone", "counterparty__name", "created_by__username")
    autocomplete_fields = ("counterparty", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DocumentExchange)
class DocumentExchangeAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "document",
        "counterparty",
        "counterparty_contact",
        "organization",
        "direction",
        "status",
        "business_document_type",
        "sent_by",
        "received_by",
        "expires_at",
        "responded_at",
    )
    list_filter = ("direction", "status", "business_document_type", "organization", "created_at", "expires_at")
    search_fields = (
        "document__title",
        "counterparty__name",
        "counterparty__email",
        "counterparty_contact__name",
        "counterparty_contact__email",
        "sent_by__username",
        "token_hint",
    )
    autocomplete_fields = ("organization", "document", "counterparty", "counterparty_contact", "sent_by", "received_by")
    readonly_fields = (
        "token_hash",
        "token_hint",
        "opened_at",
        "received_at",
        "responded_at",
        "created_at",
        "updated_at",
    )


@admin.register(ExchangeEvent)
class ExchangeEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "exchange", "document", "event_type", "actor_name", "actor_email")
    list_filter = ("event_type", "organization", "created_at")
    search_fields = ("document__title", "exchange__counterparty__name", "actor_name", "actor_email", "comment")
    autocomplete_fields = ("organization", "exchange", "document")
    readonly_fields = ("created_at", "ip_address", "user_agent")


@admin.register(ExchangeMessage)
class ExchangeMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "exchange", "document", "author_type", "user", "counterparty_contact")
    list_filter = ("author_type", "organization", "created_at")
    search_fields = (
        "document__title",
        "exchange__counterparty__name",
        "counterparty_contact__name",
        "counterparty_contact__email",
        "user__username",
        "body",
    )
    autocomplete_fields = ("organization", "exchange", "document", "counterparty", "counterparty_contact", "user")
    readonly_fields = ("created_at", "ip_address", "user_agent")


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organization", "event_type", "source", "quantity", "document", "user")
    list_filter = ("event_type", "organization", "source", "created_at")
    search_fields = ("event_type", "source", "document__title", "user__username")
    autocomplete_fields = ("organization", "document", "user")
    readonly_fields = ("created_at",)


class PlanQuotaInline(admin.TabularInline):
    model = PlanQuota
    extra = 0


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "billing_interval", "price_amount", "currency", "is_active", "created_at")
    list_filter = ("billing_interval", "currency", "is_active")
    search_fields = ("name", "code", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = (PlanQuotaInline,)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan", "status", "current_period_start", "current_period_end", "is_default")
    list_filter = ("status", "plan", "is_default", "current_period_end")
    search_fields = ("organization__name", "organization__slug", "plan__name", "plan__code")
    autocomplete_fields = ("organization", "plan", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PlanQuota)
class PlanQuotaAdmin(admin.ModelAdmin):
    list_display = ("plan", "usage_event_type", "limit", "is_unlimited")
    list_filter = ("plan", "usage_event_type", "is_unlimited")
    search_fields = ("plan__name", "plan__code", "usage_event_type")
    autocomplete_fields = ("plan",)


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "url", "is_active", "created_by", "created_at")
    list_filter = ("is_active", "organization", "created_at")
    search_fields = ("name", "url", "created_by__username")
    autocomplete_fields = ("organization", "created_by")
    readonly_fields = ("secret_hash", "created_at", "updated_at")


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "endpoint", "organization", "event_type", "status", "attempt_count", "response_status")
    list_filter = ("status", "event_type", "organization", "created_at")
    search_fields = ("endpoint__name", "endpoint__url", "event_type", "last_error")
    autocomplete_fields = ("organization", "endpoint", "usage_event")
    readonly_fields = ("created_at", "updated_at")


@admin.register(IntegrationProvider)
class IntegrationProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "provider_type", "is_active", "created_at")
    list_filter = ("provider_type", "is_active", "created_at")
    search_fields = ("name", "code", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "provider", "status", "last_sync_at", "created_by", "created_at")
    list_filter = ("status", "provider", "organization", "created_at")
    search_fields = ("name", "organization__name", "provider__name", "provider__code", "secret_ref")
    autocomplete_fields = ("organization", "provider", "created_by")
    readonly_fields = ("created_at", "updated_at", "last_sync_at")


@admin.register(IntegrationSyncJob)
class IntegrationSyncJobAdmin(admin.ModelAdmin):
    list_display = ("created_at", "connection", "organization", "status", "processed_items", "linked_references", "failed_items")
    list_filter = ("status", "connection__provider", "organization", "created_at")
    search_fields = ("connection__name", "connection__provider__name", "error_message")
    autocomplete_fields = ("organization", "connection", "started_by")
    readonly_fields = ("created_at", "started_at", "completed_at")


@admin.register(ExternalReference)
class ExternalReferenceAdmin(admin.ModelAdmin):
    list_display = ("last_seen_at", "document", "provider", "connection", "external_type", "external_id")
    list_filter = ("provider", "connection", "external_type", "organization", "last_seen_at")
    search_fields = ("document__title", "external_id", "display_name", "external_url")
    autocomplete_fields = ("organization", "document", "provider", "connection", "sync_job")
    readonly_fields = ("first_seen_at", "last_seen_at")


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
