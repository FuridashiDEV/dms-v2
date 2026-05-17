from django.urls import path
from . import views

app_name = "dms"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("analytics/", views.analytics_dashboard, name="analytics_dashboard"),
    path("usage/", views.usage_dashboard, name="usage_dashboard"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
    path("folders/", views.folder_list, name="folder_list"),
    path("folders/create/", views.folder_create, name="folder_create"),
    path("folders/<int:pk>/edit/", views.folder_edit, name="folder_edit"),
    path("folders/<int:pk>/delete/", views.folder_delete, name="folder_delete"),
    path("documents/", views.document_list, name="document_list"),
    path("documents/<int:pk>/", views.document_detail, name="document_detail"),
    path("documents/<int:pk>/relations/add/", views.document_relation_add, name="document_relation_add"),
    path(
        "documents/<int:pk>/relations/<int:relation_pk>/delete/",
        views.document_relation_delete,
        name="document_relation_delete",
    ),
    path("documents/<int:pk>/evidence/report/", views.document_evidence_report, name="document_evidence_report"),
    path("documents/<int:pk>/evidence/export/", views.document_evidence_export, name="document_evidence_export"),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path("documents/import/", views.document_import, name="document_import"),
    path("imports/<int:pk>/", views.import_batch_detail, name="import_batch_detail"),
    path("exchanges/", views.exchange_list, name="exchange_list"),
    path("exchanges/<int:exchange_id>/", views.exchange_detail, name="exchange_detail"),
    path("exchanges/<int:exchange_id>/revoke/", views.exchange_revoke, name="exchange_revoke"),
    path("exchanges/<int:exchange_id>/resend/", views.exchange_resend, name="exchange_resend"),
    path("exchanges/incoming/", views.incoming_exchange_create, name="incoming_exchange_create"),
    path("documents/<int:pk>/edit/", views.document_edit, name="document_edit"),
    path("documents/<int:pk>/workflow/start/", views.document_workflow_start, name="document_workflow_start"),
    path(
        "documents/<int:pk>/workflow/<int:instance_pk>/<slug:action>/",
        views.document_workflow_action,
        name="document_workflow_action",
    ),
    path("documents/<int:pk>/exchanges/send/", views.document_exchange_send, name="document_exchange_send"),
    path("exchanges/<int:exchange_id>/messages/", views.exchange_message_create, name="exchange_message_create"),
    path("portal/exchanges/<str:token>/", views.counterparty_portal, name="counterparty_portal"),
    path(
        "portal/exchanges/<str:token>/download/",
        views.counterparty_portal_download,
        name="counterparty_portal_download",
    ),
    path(
        "portal/exchanges/<str:token>/<slug:action>/",
        views.counterparty_portal_action,
        name="counterparty_portal_action",
    ),
    path("documents/<int:pk>/ai-review/", views.document_ai_review, name="document_ai_review"),
    path("users/create/", views.user_create, name="user_create"),
    path("documents/<int:pk>/view/", views.document_view, name="document_view"),
    path("documents/<int:pk>/download/", views.document_download, name="document_download"),
    path(
        "documents/<int:pk>/versions/<int:version_pk>/view/",
        views.document_version_view,
        name="document_version_view",
    ),
    path(
        "documents/<int:pk>/versions/<int:version_pk>/download/",
        views.document_version_download,
        name="document_version_download",
    ),
    path(
    "documents/<int:pk>/access/",
    views.document_access_manage,
    name="document_access_manage",
    ),
    path(
    "documents/access/<int:pk>/revoke/",
    views.document_access_revoke,
    name="document_access_revoke"
    ),
    path("users/", views.user_list, name="user_list"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("ai/parse/", views.ai_parse_document, name="ai_parse"),
    path("search/", views.semantic_search, name="semantic_search"),
    path("users/<int:pk>/password/", views.user_change_password, name="user_change_password"),
    path(
    "documents/<int:pk>/delete/",
    views.document_delete,
    name="document_delete",
    ),
    path(
    "ajax/folders/",
    views.folders_by_department,
    name="folders_by_department",
    ),
    path("subfolders-by-parent/", views.subfolders_by_parent, name="subfolders_by_parent"),


]
