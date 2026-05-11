from django.urls import path
from . import views

app_name = "dms"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("folders/", views.folder_list, name="folder_list"),
    path("folders/create/", views.folder_create, name="folder_create"),
    path("folders/<int:pk>/edit/", views.folder_edit, name="folder_edit"),
    path("folders/<int:pk>/delete/", views.folder_delete, name="folder_delete"),
    path("documents/", views.document_list, name="document_list"),
    path("documents/<int:pk>/", views.document_detail, name="document_detail"),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path("documents/<int:pk>/edit/", views.document_edit, name="document_edit"),
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
