from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import date, timedelta
import logging
from difflib import SequenceMatcher
from .forms import (
    AiParseUploadForm,
    CounterpartyExchangeForm,
    DepartmentSelectionForm,
    DocumentAccessForm,
    DocumentRelationForm,
    DocumentSearchForm,
    DocumentUploadForm,
    ExchangeLinkResendForm,
    ExchangeListFilterForm,
    ExchangeMessageForm,
    ExternalExchangeActionForm,
    FolderBrowserQueryForm,
    ImportBatchForm,
    IncomingExchangeForm,
    FolderManageForm,
    ParentFolderSelectionForm,
    SemanticSearchForm,
    UserCreateForm,
    UserPasswordChangeForm,
    WorkflowActionForm,
    WorkflowStartForm,
)
from .models import AuditEvent, Counterparty, Department, Document, DocumentActivity, DocumentExchange, DocumentRelation, DocumentType, DocumentVersion, ExchangeEvent, ExtractedField, Folder, ImportBatch, Notification, Organization, Plan, ProcessingJob, Subscription, UsageEvent, WebhookDelivery, WorkflowInstance
from dms.services.ai_parser import parse_document
from dms.services.archive_intelligence import (
    build_card_quality,
    build_retention_assistant,
    get_superseded_candidates,
)
from dms.services.document_indexing import delete_document_from_index, index_document
from dms.services.audit import record_audit_event
from dms.services.ai_processing import apply_confirmed_fields, run_document_ai_processing
from dms.services.analytics import (
    build_observability_summary,
    build_organization_metrics,
    build_platform_metrics,
    parse_date_range,
)
from dms.services.billing import change_subscription_plan, get_billing_overview, get_usage_vs_limits
from dms.services.cost_optimization import build_cost_dashboard_report
from dms.services.document_creation import create_document_from_uploaded_file
from dms.services.document_relations import (
    build_document_relation_graph,
    can_manage_document_relations,
    create_document_relation,
    delete_document_relation,
    get_visible_document_relations,
    suggest_document_relations,
)
from dms.services.evidence import build_document_evidence_package
from dms.services.evidence_report import build_evidence_report_context
from dms.services.enterprise_security import (
    build_audit_export_response,
    build_security_summary,
    get_security_events,
    get_security_organizations,
    user_can_view_security,
)
from dms.services.security import protected_file_response
from dms.services.search_intelligence import build_search_query
from dms.services.search_experience import (
    SEARCH_MODE_EXACT,
    SEARCH_MODE_HYBRID,
    SEARCH_MODE_SEMANTIC,
    accessible_related_documents_for_search,
    apply_experience_filters,
    build_lexical_filter,
    build_search_snippet,
    matched_entities_for_document,
    normalize_search_mode,
)
from dms.services.reranking import fuse_candidates, rank_documents_for_search
from dms.services.usage import record_usage_event
from dms.services.counterparty import (
    ExchangeError,
    ExchangePermissionError,
    accept_exchange,
    can_send_document_exchange,
    comment_exchange,
    create_document_exchange,
    create_incoming_document_exchange,
    expire_exchange,
    is_exchange_expired,
    mark_exchange_opened,
    record_exchange_download,
    record_exchange_message,
    reissue_exchange_link,
    reject_exchange,
    revoke_exchange_link,
    resolve_exchange_token,
)
from dms.services.imports import create_import_batch, import_uploaded_files
from dms.services.workflow import (
    WorkflowError,
    WorkflowPermissionError,
    approve_workflow,
    can_act_on_workflow,
    can_start_workflow,
    comment_workflow,
    get_active_workflow,
    reject_workflow,
    request_workflow_changes,
    start_workflow,
)
import tempfile

from dms.services.text_extractor import extract_text_from_file
import os
import re
User = get_user_model()
from dms.utils import get_allowed_departments, get_allowed_documents, get_user_organizations, user_can_access_document

logger = logging.getLogger(__name__)

SEARCH_STOPWORDS = {
    "и", "или", "в", "во", "на", "по", "от", "до", "для", "из", "к", "ко",
    "о", "об", "это", "как", "что", "не", "но", "а", "же", "ли", "у",
}

CYRILLIC_TO_LATIN = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _get_login_rate_limit_key(request):
    username = (request.POST.get("username") or "").strip().lower()
    ip_address = _get_client_ip(request)
    return f"login-rate-limit:{ip_address}:{username or 'anonymous'}"


def _is_login_rate_limited(request):
    attempts = cache.get(_get_login_rate_limit_key(request), 0)
    return attempts >= settings.LOGIN_RATE_LIMIT_ATTEMPTS


def _register_login_failure(request):
    key = _get_login_rate_limit_key(request)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, timeout=settings.LOGIN_RATE_LIMIT_WINDOW)


def _reset_login_failures(request):
    cache.delete(_get_login_rate_limit_key(request))


def _normalize_search_text(value: str) -> str:
    cleaned = re.sub(r"[^\w\s-]+", " ", (value or "").lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _transliterate_to_latin(value: str) -> str:
    return (value or "").lower().translate(CYRILLIC_TO_LATIN)


def _tokenize_search_query(value: str) -> list[str]:
    normalized = _normalize_search_text(value)
    tokens = []
    for token in normalized.split():
        if len(token) < 3 or token in SEARCH_STOPWORDS:
            continue
        tokens.append(token)
        transliterated = _transliterate_to_latin(token)
        if transliterated and transliterated != token and len(transliterated) >= 3:
            tokens.append(transliterated)
    return list(dict.fromkeys(tokens))


def _field_match_score(field_value: str, query_tokens: list[str]) -> float:
    if not field_value or not query_tokens:
        return 0.0

    normalized = _normalize_search_text(field_value)
    transliterated = _transliterate_to_latin(normalized)
    field_tokens = set(normalized.split())
    transliterated_tokens = set(transliterated.split())
    best_scores: list[float] = []

    for token in query_tokens:
        best = 0.0
        if token in normalized or token in transliterated:
            best = 1.0
        else:
            for candidate in field_tokens | transliterated_tokens:
                if len(candidate) < 3:
                    continue
                shares_prefix = candidate[:3] == token[:3]
                contains_core = token in candidate or candidate in token
                if not shares_prefix and not contains_core:
                    continue
                ratio = SequenceMatcher(None, token, candidate).ratio()
                if ratio > best:
                    best = ratio
        if best >= 0.66:
            best_scores.append(best)

    if not best_scores:
        return 0.0

    coverage = len(best_scores) / len(query_tokens)
    average_quality = sum(best_scores) / len(best_scores)
    return round(min(1.0, coverage * 0.55 + average_quality * 0.45), 4)


def _document_lexical_score(doc, query_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0

    title_score = _field_match_score(doc.title, query_tokens)
    description_score = _field_match_score(doc.description, query_tokens)
    filename_score = _field_match_score(doc.source_file_name or "", query_tokens)
    folder_score = _field_match_score(doc.folder.name if doc.folder else "", query_tokens)
    type_score = _field_match_score(doc.doc_type.name if doc.doc_type else "", query_tokens)
    text_score = _field_match_score((doc.extracted_text or "")[:1600], query_tokens)

    score = (
        title_score * 0.34
        + description_score * 0.34
        + filename_score * 0.18
        + text_score * 0.1
        + folder_score * 0.04
        + type_score * 0.0
    )
    return round(min(score, 1.0), 4)


def document_snapshot_changed(original, updated):
    fields = [
        "title",
        "description",
        "doc_type_id",
        "doc_date",
        "department_id",
        "folder_id",
        "language",
        "document_author",
        "retention_category",
        "retention_until",
        "legal_hold",
        "extracted_text",
        "source_file_name",
        "mime_type",
        "checksum_sha256",
        "source_system",
        "format_risk_level",
        "file",
    ]
    for field in fields:
        if getattr(original, field) != getattr(updated, field):
            return True
    return False


def populate_preservation_metadata(doc, uploaded_file=None):
    if uploaded_file is not None:
        doc.source_file_name = uploaded_file.name
        doc.mime_type = detect_mime_type(uploaded_file.name)
        doc.format_risk_level = detect_format_risk(uploaded_file.name)
    elif doc.file:
        doc.source_file_name = doc.source_file_name or os.path.basename(doc.file.name)
        doc.mime_type = doc.mime_type or detect_mime_type(doc.source_file_name or doc.file.name)
        doc.format_risk_level = (
            doc.format_risk_level
            if doc.format_risk_level and doc.format_risk_level != Document.FormatRisk.UNKNOWN
            else detect_format_risk(doc.source_file_name or doc.file.name)
        )

    checksum_sha256 = ""
    if uploaded_file is not None:
        checksum_sha256 = calculate_file_sha256(uploaded_file)
    if not checksum_sha256 and doc.file:
        checksum_sha256 = calculate_file_sha256(doc.file)
    if not checksum_sha256 and doc.file and getattr(doc.file, "path", None):
        checksum_sha256 = calculate_sha256(doc.file.path)
    if checksum_sha256:
        doc.checksum_sha256 = checksum_sha256


def get_status_badge_meta(status: str) -> tuple[str, str]:
    mapping = {
        Document.Status.DRAFT: ("Черновик", "badge-status-draft"),
        Document.Status.APPROVED: ("Актуальный", "badge-status-approved"),
        Document.Status.ARCHIVED: ("В архиве", "badge-status-archived"),
    }
    return mapping.get(status, ("Неизвестно", "badge-status-draft"))


def _build_filename_metadata(filename: str, allowed_types: set[str]) -> dict:
    stem = os.path.splitext(os.path.basename(filename))[0]
    normalized = re.sub(r"[_]+", " ", stem)
    normalized = re.sub(r"\s+", " ", normalized).strip(" -_.")

    title = normalized[:180]
    summary = f"Метаданные заполнены по имени файла: {normalized}" if normalized else ""

    date_value = None
    date_match = re.search(r"(\d{2})[.\-_](\d{2})[.\-_](\d{4})", normalized)
    if date_match:
        day, month, year = date_match.groups()
        date_value = f"{year}-{month}-{day}"

    doc_type = extract_doc_type(normalized)
    if doc_type and allowed_types:
        lowered = doc_type.lower()
        doc_type = next(
            (item for item in allowed_types if item.lower() == lowered),
            doc_type,
        )

    return {
        "title_ru": title,
        "title_kk": "",
        "summary_ru": summary,
        "summary_kk": "",
        "doc_type": doc_type,
        "date": date_value,
    }


def _detect_document_language(*values: str) -> str:
    text = " ".join(v for v in values if isinstance(v, str))
    lowered = text.lower()
    if re.search(r"[әғқңөұүһі]", lowered):
        return Document.Language.KK
    if re.search(r"[а-яё]", lowered) and re.search(r"[a-z]", lowered):
        return Document.Language.MIXED
    if re.search(r"[а-яё]", lowered):
        return Document.Language.RU
    if re.search(r"[a-z]", lowered):
        return Document.Language.EN
    return Document.Language.UNKNOWN


def _retention_years_for(doc_type: str | None, title: str = "", text: str = "") -> int:
    basis = " ".join(filter(None, [doc_type or "", title, text])).lower()
    if any(token in basis for token in ["положение", "правила", "регламент"]):
        return 10
    if any(token in basis for token in ["договор", "agreement", "контракт"]):
        return 5
    if any(token in basis for token in ["приказ", "распоряжение"]):
        return 5
    if any(token in basis for token in ["хат", "письмо", "служеб", "записк"]):
        return 3
    return 5


def _retention_category_for(doc_type: str | None, title: str = "", text: str = "") -> str:
    basis = " ".join(filter(None, [doc_type or "", title, text])).lower()
    if any(token in basis for token in ["положение", "правила", "регламент"]):
        return "Нормативный документ"
    if any(token in basis for token in ["договор", "agreement", "контракт"]):
        return "Договорной документ"
    if any(token in basis for token in ["приказ", "распоряжение"]):
        return "Организационно-распорядительный документ"
    if any(token in basis for token in ["хат", "письмо", "служеб", "записк"]):
        return "Служебная переписка"
    return "Общий документ"


def _add_years_safe(value: str | None, years: int) -> str | None:
    if not value:
        return None
    try:
        dt = date.fromisoformat(value)
    except ValueError:
        return None
    try:
        return dt.replace(year=dt.year + years).isoformat()
    except ValueError:
        return dt.replace(month=2, day=28, year=dt.year + years).isoformat()


def _build_autofill_metadata(
    *,
    filename: str,
    allowed_types: set[str],
    user,
    text: str = "",
    ai_meta: dict | None = None,
    date_value: str | None = None,
) -> dict:
    base = _build_filename_metadata(filename, allowed_types)
    ai_meta = ai_meta or {}

    title_ru = ai_meta.get("title_ru") or base.get("title_ru") or ""
    summary_ru = ai_meta.get("summary_ru") or base.get("summary_ru") or ""
    doc_type = ai_meta.get("doc_type") or base.get("doc_type")
    resolved_date = date_value or base.get("date")
    language = ai_meta.get("language") or _detect_document_language(text, filename, title_ru, summary_ru)
    author = (ai_meta.get("document_author") or "").strip()
    if not author:
        author = user.get_full_name().strip() if user and hasattr(user, "get_full_name") else ""
    if not author and user:
        author = getattr(user, "username", "") or ""
    retention_category = (ai_meta.get("retention_category") or "").strip() or _retention_category_for(doc_type, title_ru, text)
    retention_until = _add_years_safe(resolved_date, _retention_years_for(doc_type, title_ru, text))

    return {
        "title_ru": title_ru,
        "title_kk": ai_meta.get("title_kk", ""),
        "summary_ru": summary_ru,
        "summary_kk": ai_meta.get("summary_kk", ""),
        "doc_type": doc_type,
        "date": resolved_date,
        "language": language,
        "document_author": author,
        "status": Document.Status.DRAFT,
        "retention_category": retention_category,
        "retention_until": retention_until,
        "source_system": f"Веб-загрузка: {os.path.basename(filename)}",
        "legal_hold": bool(ai_meta.get("legal_hold", False)),
    }


def build_document_form_context(
    *,
    form,
    user,
    doc=None,
    versions=None,
    mode: str,
):
    selected_department_id = None
    selected_root_folder_id = None
    selected_subfolder_id = None

    if form.data.get("department", "").isdigit():
        selected_department_id = int(form.data.get("department"))
    elif doc and doc.department_id:
        selected_department_id = doc.department_id
    elif user.role != "ADMIN" and user.department_id:
        selected_department_id = user.department_id

    if form.data.get("subfolder", "").isdigit():
        selected_subfolder_id = int(form.data.get("subfolder"))

    if form.data.get("folder", "").isdigit():
        selected_root_folder_id = int(form.data.get("folder"))
    elif doc and doc.folder_id:
        if doc.folder.parent_id:
            selected_root_folder_id = doc.folder.parent_id
            selected_subfolder_id = selected_subfolder_id or doc.folder_id
        else:
            selected_root_folder_id = doc.folder_id

    root_folders = Folder.objects.none()
    current_subfolders = Folder.objects.none()

    if selected_department_id:
        root_folders = Folder.objects.filter(
            department_id=selected_department_id,
            parent__isnull=True,
        ).order_by("tree_id", "lft")

    if selected_root_folder_id:
        current_subfolders = Folder.objects.filter(
            parent_id=selected_root_folder_id
        ).order_by("tree_id", "lft")

    selected_access_department_ids = []
    if hasattr(form, "fields") and "access_departments" in form.fields:
        raw_values = form["access_departments"].value() or []
        selected_access_department_ids = [str(value) for value in raw_values]

    return {
        "form": form,
        "doc": doc,
        "versions": versions or [],
        "mode": mode,
        "page_title": "Загрузить документ" if mode == "create" else "Изменить документ",
        "page_subtitle": (
            "Заполните карточку документа, загрузите файл и поместите его в нужную папку архива."
            if mode == "create"
            else "Обновите реквизиты, файл или архивный контекст документа без расхождения интерфейсов."
        ),
        "submit_label": "Сохранить документ" if mode == "create" else "Сохранить изменения",
        "selected_department_id": str(selected_department_id or ""),
        "selected_root_folder_id": str(selected_root_folder_id or ""),
        "selected_subfolder_id": str(selected_subfolder_id or ""),
        "root_folders": root_folders,
        "current_subfolders": current_subfolders,
        "selected_access_department_ids": selected_access_department_ids,
        "show_access_block": mode == "create",
    }




# =========================================================
# AUTH
# =========================================================
class CustomLoginView(LoginView):
    template_name = "auth/login.html"

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST" and _is_login_rate_limited(request):
            record_audit_event(
                event_type="SECURITY_LOGIN_RATE_LIMITED",
                request=request,
                metadata={
                    "username": (request.POST.get("username") or "").strip().lower()[:150],
                    "control": "login_rate_limit",
                },
            )
            form = self.get_form()
            form.add_error(None, "Слишком много попыток входа. Повторите позже.")
            return self.form_invalid(form)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        _reset_login_failures(self.request)
        record_audit_event(
            event_type="SECURITY_LOGIN_SUCCESS",
            request=self.request,
            user=form.get_user(),
            metadata={"control": "login"},
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.method == "POST" and not _is_login_rate_limited(self.request):
            _register_login_failure(self.request)
            record_audit_event(
                event_type="SECURITY_LOGIN_FAILURE",
                request=self.request,
                metadata={
                    "username": (self.request.POST.get("username") or "").strip().lower()[:150],
                    "control": "login",
                },
            )
        return super().form_invalid(form)


@login_required
def logout_view(request):
    logout(request)
    return redirect("/login/")


def can_manage_users(user):
    if not user.is_authenticated:
        return False

    if user.role == "ADMIN":
        return True

    if user.department and user.department.name == "Управление по работе с персоналом":
        return True

    return False



# =========================================================
# HELPERS (доступ по оргструктуре)
# =========================================================
def _deprecated_get_allowed_departments(user):
    """
    ADMIN: все отделы
    остальные: свой отдел + все нижестоящие (descendants)
    """
    return get_allowed_departments(user)


# =========================================================
# DASHBOARD
# =========================================================
@login_required
def dashboard(request):
    user = request.user

    allowed_depts = get_allowed_departments(user)
    if user.role != "ADMIN" and not allowed_depts.exists():
        return HttpResponseForbidden("У вас не указан отдел")

    # --- документы, доступные пользователю
    docs_qs = get_allowed_documents(user)
    now = timezone.now()
    month_start = now.replace(day=1)

    total_count = docs_qs.count()
    month_count = docs_qs.filter(created_at__gte=month_start).count()

    # --- последние действия пользователя
    activities = (
        DocumentActivity.objects
        .filter(user=user)
        .select_related("document", "document__department", "document__doc_type")
        .order_by("-created_at")[:5]
    )

    context = {
        "total_count": total_count,
        "month_count": month_count,
        "system_status": "active",
        "activities": activities,
    }

    return render(request, "dms/dashboard.html", context)


@login_required
def usage_dashboard(request):
    organizations = get_user_organizations(request.user)
    usage_events = (
        UsageEvent.objects
        .filter(organization__in=organizations)
        .select_related("organization", "user", "document")
        .order_by("-created_at")[:100]
    )
    usage_summary = (
        UsageEvent.objects
        .filter(organization__in=organizations)
        .values("event_type")
        .annotate(total=Count("id"), quantity=Sum("quantity"))
        .order_by("event_type")
    )
    webhook_deliveries = (
        WebhookDelivery.objects
        .filter(organization__in=organizations)
        .select_related("endpoint", "usage_event")
        .order_by("-created_at")[:50]
    )
    return render(
        request,
        "dms/usage_dashboard.html",
        {
            "usage_events": usage_events,
            "usage_summary": usage_summary,
            "webhook_deliveries": webhook_deliveries,
        },
    )


@login_required
def billing_dashboard(request):
    if not request.user.is_superuser and request.user.role != "ADMIN":
        return HttpResponseForbidden("Billing is available to organization admins.")

    if request.user.is_superuser:
        allowed_organizations = Organization.objects.filter(is_active=True).order_by("name", "id")
    else:
        allowed_organizations = get_user_organizations(request.user).order_by("name", "id")

    selected_organization_id = request.POST.get("organization") or request.GET.get("organization")
    if selected_organization_id:
        selected_organization = get_object_or_404(allowed_organizations, id=selected_organization_id)
    else:
        selected_organization = allowed_organizations.first()

    if selected_organization is None:
        return HttpResponseForbidden("No organization available.")

    if request.method == "POST":
        if not request.user.is_superuser:
            return HttpResponseForbidden("Only superuser can change subscription plan.")
        plan = get_object_or_404(Plan.objects.filter(is_active=True), code=request.POST.get("plan_code", ""))
        status = request.POST.get("status") or Subscription.Status.ACTIVE
        try:
            change_subscription_plan(
                organization=selected_organization,
                plan=plan,
                status=status,
                changed_by=request.user,
                reason=request.POST.get("reason", ""),
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Subscription plan changed.")
        return redirect(f"{reverse('dms:billing_dashboard')}?organization={selected_organization.id}")

    overview = get_billing_overview(selected_organization)
    plans = Plan.objects.filter(is_active=True).order_by("name")
    status_choices = Subscription.Status.choices
    return render(
        request,
        "dms/billing_dashboard.html",
        {
            "allowed_organizations": allowed_organizations,
            "selected_organization": selected_organization,
            "overview": overview,
            "plans": plans,
            "status_choices": status_choices,
            "is_platform_admin": request.user.is_superuser,
        },
    )


@login_required
def billing_usage_limits(request):
    if not request.user.is_superuser and request.user.role != "ADMIN":
        return HttpResponseForbidden("Billing usage is available to organization admins.")

    if request.user.is_superuser:
        allowed_organizations = Organization.objects.filter(is_active=True).order_by("name", "id")
    else:
        allowed_organizations = get_user_organizations(request.user).order_by("name", "id")

    selected_organization_id = request.GET.get("organization")
    if selected_organization_id:
        selected_organization = get_object_or_404(allowed_organizations, id=selected_organization_id)
    else:
        selected_organization = allowed_organizations.first()

    if selected_organization is None:
        return HttpResponseForbidden("No organization available.")

    report = get_usage_vs_limits(selected_organization)
    return render(
        request,
        "dms/billing_usage_limits.html",
        {
            "allowed_organizations": allowed_organizations,
            "selected_organization": selected_organization,
            "report": report,
            "is_platform_admin": request.user.is_superuser,
        },
    )


@login_required
def cost_optimization_dashboard(request):
    if not request.user.is_superuser and request.user.role != "ADMIN":
        return HttpResponseForbidden("Cost optimization is available to organization admins.")

    if request.user.is_superuser:
        allowed_organizations = Organization.objects.filter(is_active=True).order_by("name", "id")
    else:
        allowed_organizations = get_user_organizations(request.user).order_by("name", "id")

    selected_organization_id = request.GET.get("organization")
    if selected_organization_id:
        selected_organization = get_object_or_404(allowed_organizations, id=selected_organization_id)
    else:
        selected_organization = allowed_organizations.first()

    if selected_organization is None:
        return HttpResponseForbidden("No organization available.")

    return render(
        request,
        "dms/cost_optimization_dashboard.html",
        {
            "allowed_organizations": allowed_organizations,
            "selected_organization": selected_organization,
            "report": build_cost_dashboard_report(selected_organization),
            "is_platform_admin": request.user.is_superuser,
        },
    )


@login_required
def security_dashboard(request):
    if not user_can_view_security(request.user):
        return HttpResponseForbidden("Security dashboard is available to organization admins.")

    allowed_organizations = get_security_organizations(request.user)
    selected_organization_id = request.GET.get("organization")
    if selected_organization_id:
        selected_organization = get_object_or_404(allowed_organizations, id=selected_organization_id)
    else:
        selected_organization = allowed_organizations.first()

    if selected_organization is None:
        return HttpResponseForbidden("No organization available.")

    return render(
        request,
        "dms/security_dashboard.html",
        {
            "allowed_organizations": allowed_organizations,
            "selected_organization": selected_organization,
            "summary": build_security_summary(user=request.user, organization=selected_organization),
            "security_events": get_security_events(
                user=request.user,
                organization=selected_organization,
                limit=100,
            ),
            "is_platform_admin": request.user.is_superuser,
        },
    )


@login_required
def security_audit_export(request):
    if not user_can_view_security(request.user):
        return HttpResponseForbidden("Audit export is available to organization admins.")

    allowed_organizations = get_security_organizations(request.user)
    selected_organization = None
    selected_organization_id = request.GET.get("organization")
    if selected_organization_id:
        selected_organization = get_object_or_404(allowed_organizations, id=selected_organization_id)

    response = build_audit_export_response(
        user=request.user,
        organization=selected_organization,
    )
    record_audit_event(
        event_type="SECURITY_AUDIT_EXPORTED",
        request=request,
        organization=selected_organization,
        metadata={
            "organization_id": selected_organization.id if selected_organization else None,
            "scope": "selected_organization" if selected_organization else "allowed_organizations",
            "format": "csv",
        },
    )
    return response


@login_required
def analytics_dashboard(request):
    date_range = parse_date_range(request.GET)
    if request.user.is_superuser:
        allowed_organizations = Organization.objects.filter(is_active=True).order_by("name", "id")
    else:
        allowed_organizations = get_user_organizations(request.user).order_by("name", "id")
    selected_organization = None
    organization_metrics = None
    platform_metrics = None

    if request.user.is_superuser:
        platform_metrics = build_platform_metrics(date_range)
        selected_organization_id = request.GET.get("organization")
        if selected_organization_id:
            selected_organization = get_object_or_404(Organization, id=selected_organization_id, is_active=True)
        else:
            selected_organization = allowed_organizations.first() or Organization.objects.filter(is_active=True).order_by("name", "id").first()
    else:
        selected_organization_id = request.GET.get("organization")
        if selected_organization_id:
            selected_organization = get_object_or_404(allowed_organizations, id=selected_organization_id)
        else:
            selected_organization = allowed_organizations.first()

    if selected_organization is not None:
        if not request.user.is_superuser and not allowed_organizations.filter(id=selected_organization.id).exists():
            raise Http404
        organization_metrics = build_organization_metrics(selected_organization, date_range)
    observability_organizations = allowed_organizations
    if not request.user.is_superuser and selected_organization is not None:
        observability_organizations = allowed_organizations.filter(id=selected_organization.id)
    observability_metrics = build_observability_summary(
        observability_organizations,
        date_range,
    )

    return render(
        request,
        "dms/analytics_dashboard.html",
        {
            "date_range": date_range,
            "allowed_organizations": allowed_organizations,
            "selected_organization": selected_organization,
            "organization_metrics": organization_metrics,
            "platform_metrics": platform_metrics,
            "observability_metrics": observability_metrics,
            "is_platform_view": request.user.is_superuser,
        },
    )


from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from dms.models import Document, DocumentType, Department, Folder
from dms.services.embedding import build_embedding
from dms.services.vector_store import search_documents


@login_required
def document_list(request):
    user = request.user
    allowed_depts = get_allowed_departments(user).order_by("tree_id", "lft")
    if user.role != "ADMIN" and not user.department_id:
        return HttpResponseForbidden("У вас не указан отдел")

    filter_form = DocumentSearchForm(
        request.GET or None,
        allowed_departments=allowed_depts,
    )
    if request.GET and not filter_form.is_valid():
        return HttpResponseBadRequest("Некорректные параметры фильтрации.")

    cleaned_filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = cleaned_filters.get("q", "")
    requested_search_mode = normalize_search_mode(cleaned_filters.get("search_mode") or SEARCH_MODE_HYBRID)
    doc_type_id = cleaned_filters.get("doc_type")
    department_id = cleaned_filters.get("department")
    folder_id = cleaned_filters.get("folder")
    counterparty = cleaned_filters.get("counterparty", "")
    amount_min = cleaned_filters.get("amount_min")
    amount_max = cleaned_filters.get("amount_max")
    status = cleaned_filters.get("status") or ""
    date_from = cleaned_filters.get("date_from")
    date_to = cleaned_filters.get("date_to")

    base_qs = (
        get_allowed_documents(user)
        .select_related("department", "doc_type", "uploaded_by", "folder")
        .prefetch_related("versions")
    )

    if doc_type_id:
        base_qs = base_qs.filter(doc_type_id=doc_type_id)

    if department_id:
        base_qs = base_qs.filter(department_id=department_id)

    if folder_id:
        base_qs = base_qs.filter(folder_id=folder_id)

    base_qs = apply_experience_filters(
        base_qs,
        counterparty=counterparty,
        amount_min=amount_min,
        amount_max=amount_max,
    )

    if status in {
        Document.Status.DRAFT,
        Document.Status.APPROVED,
        Document.Status.ARCHIVED,
    }:
        base_qs = base_qs.filter(status=status)

    if date_from is not None:
        base_qs = base_qs.filter(doc_date__gte=date_from)

    if date_to is not None:
        base_qs = base_qs.filter(doc_date__lte=date_to)

    search_mode = "browse"
    lexical_ids: list[int] = []
    semantic_ids: list[int] = []
    semantic_score_map: dict[int, float] = {}
    search_degraded = False

    if q:
        search_query = build_search_query(q)
        lexical_filter = build_lexical_filter(q, search_query)
        lexical_qs = base_qs.filter(lexical_filter).order_by("-doc_date", "-created_at")
        fallback_lexical_ids = list(lexical_qs.values_list("id", flat=True)[:120])
        exact_ids = list(
            base_qs.filter(
                Q(title__iexact=q)
                | Q(source_file_name__iexact=q)
            ).values_list("id", flat=True)[:40]
        )
        entity_filter = Q()
        for key in ("document_type", "counterparty", "subject", "document_number", "document_date", "bin_iin", "contract_reference"):
            value = search_query.entities.get(key)
            if value:
                entity_filter |= Q(**{f"search_entities__{key}__icontains": value})
        amount_value = (search_query.entities.get("amount") or {}).get("value")
        if amount_value:
            entity_filter |= Q(search_entities__amount__value=amount_value)
        entity_ids = list(base_qs.filter(entity_filter).values_list("id", flat=True)[:80]) if entity_filter else []
        alias_filter = Q()
        for values in search_query.aliases.values():
            for value in values[:12]:
                if value and len(str(value)) > 1:
                    alias_filter |= Q(search_text_normalized__icontains=str(value))
        alias_ids = list(base_qs.filter(alias_filter).values_list("id", flat=True)[:80]) if alias_filter else []

        if requested_search_mode in {SEARCH_MODE_HYBRID, SEARCH_MODE_EXACT}:
            lexical_ids = fallback_lexical_ids

        embedding = []
        if requested_search_mode in {SEARCH_MODE_HYBRID, SEARCH_MODE_SEMANTIC}:
            embedding = build_embedding(search_query.expanded_text)
        if embedding:
            try:
                semantic_hits = search_documents(
                    embedding=embedding,
                    limit=120,
                    filters={
                        "organization_id": list(get_user_organizations(user).values_list("id", flat=True)),
                    },
                )
                semantic_ids = []
                for hit in semantic_hits:
                    doc_id_value = hit.get("document_id") or hit.get("id")
                    if not doc_id_value:
                        continue
                    doc_id = int(doc_id_value)
                    semantic_ids.append(doc_id)
                    semantic_score_map[doc_id] = max(
                        semantic_score_map.get(doc_id, 0.0),
                        float(hit.get("score") or 0.0),
                    )
            except Exception:
                semantic_ids = []
                semantic_score_map = {}
                search_degraded = True
        elif requested_search_mode == SEARCH_MODE_SEMANTIC:
            search_degraded = True

        if requested_search_mode == SEARCH_MODE_SEMANTIC and not semantic_ids:
            lexical_ids = fallback_lexical_ids

        seed_ids = list(dict.fromkeys([*exact_ids, *entity_ids, *lexical_ids, *alias_ids, *semantic_ids]))
        related_ids: list[int] = []
        if seed_ids:
            relation_rows = (
                DocumentRelation.objects
                .filter(
                    Q(from_document_id__in=seed_ids) | Q(to_document_id__in=seed_ids),
                    is_confirmed=True,
                )
                .values_list("from_document_id", "to_document_id")[:120]
            )
            related_candidates = []
            seed_set = set(seed_ids)
            for from_id, to_id in relation_rows:
                if from_id in seed_set and to_id not in seed_set:
                    related_candidates.append(to_id)
                elif to_id in seed_set and from_id not in seed_set:
                    related_candidates.append(from_id)
            if related_candidates:
                related_ids = list(
                    base_qs.filter(id__in=list(dict.fromkeys(related_candidates)))
                    .values_list("id", flat=True)[:40]
                )

        fused_candidates = fuse_candidates(
            exact_ids=exact_ids,
            entity_ids=entity_ids,
            text_ids=lexical_ids,
            alias_ids=alias_ids,
            vector_scores=semantic_score_map,
            related_ids=related_ids,
        )
        combined_ids = list(fused_candidates.keys())

        if combined_ids:
            candidate_docs = list(base_qs.filter(id__in=combined_ids))
            ranked_results = rank_documents_for_search(
                documents=candidate_docs,
                search_query=search_query,
                fused_candidates=fused_candidates,
            )
            documents = []
            for result in ranked_results[:80]:
                doc = result.document
                doc.search_explanation = result.reasons or ["matched available document text"]
                doc.search_confidence = result.confidence
                doc.search_final_score = result.final_score
                doc.search_candidate_sources = result.sources
                documents.append(doc)
        else:
            documents = []

        if lexical_ids and semantic_ids:
            search_mode = "hybrid"
        elif semantic_ids:
            search_mode = "semantic"
        else:
            search_mode = "text"
        if requested_search_mode == SEARCH_MODE_EXACT:
            search_mode = "exact"
        elif requested_search_mode == SEARCH_MODE_SEMANTIC and search_degraded:
            search_mode = "semantic_fallback"
        record_audit_event(
            event_type=AuditEvent.EventType.DOCUMENT_SEARCHED,
            request=request,
            user=request.user,
            organization=get_user_organizations(user).first(),
            metadata={
                "search_mode": search_mode,
                "requested_search_mode": requested_search_mode,
                "search_text_length": len(q or ""),
                "result_count": len(documents),
                "search_degraded": search_degraded,
                "has_filters": any([doc_type_id, department_id, folder_id, counterparty, amount_min, amount_max, status, date_from, date_to]),
                "search_entity_keys": sorted((search_query.entities or {}).keys()) if search_query else [],
                "alias_count": len(search_query.aliases or {}) if search_query else 0,
            },
        )
    else:
        search_query = None
        documents = list(base_qs.order_by("-doc_date", "-created_at")[:120])

    allowed_documents_for_relations = get_allowed_documents(user).only("id")
    for doc in documents:
        doc.can_manage_access = (
            user.role == "ADMIN"
            or doc.uploaded_by_id == user.id
            or doc.department_id == user.department_id
        )
        doc.version_count = len(doc.versions.all()) or 1
        doc.status_label, doc.status_badge = get_status_badge_meta(doc.status)
        doc.folder_path = _folder_path(doc.folder) if doc.folder else "Без папки"
        doc.search_snippet = build_search_snippet(doc, search_query)
        doc.search_matched_entities = matched_entities_for_document(doc, search_query)
        doc.search_related_documents = accessible_related_documents_for_search(
            doc,
            allowed_documents_for_relations,
        )

    selected_department = None
    if department_id:
        selected_department = allowed_depts.filter(id=department_id).first()

    selected_folder = None
    if folder_id:
        selected_folder = Folder.objects.filter(
            id=folder_id,
            department__in=allowed_depts,
        ).first()

    selected_doc_type = None
    if doc_type_id:
        selected_doc_type = DocumentType.objects.filter(
            id=doc_type_id,
            organization__in=get_user_organizations(user),
        ).first()

    status_choices = [
        (Document.Status.DRAFT, "Черновики"),
        (Document.Status.APPROVED, "Актуальные"),
        (Document.Status.ARCHIVED, "Архивные"),
    ]

    context = {
        "documents": documents,
        "q": q,
        "doc_types": DocumentType.objects.filter(
            organization__in=get_user_organizations(user),
        ).order_by("name"),
        "departments": allowed_depts,
        "folders": Folder.objects.filter(
            department__in=allowed_depts
        ).order_by("tree_id", "lft"),
        "doc_type_id": str(doc_type_id or ""),
        "department_id": str(department_id or ""),
        "folder_id": str(folder_id or ""),
        "counterparty": counterparty,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "status": status,
        "status_choices": status_choices,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "result_count": len(documents),
        "search_mode": search_mode,
        "requested_search_mode": requested_search_mode,
        "search_mode_choices": DocumentSearchForm.SEARCH_MODE_CHOICES,
        "search_degraded": search_degraded,
        "query_entities": search_query.entities if q and search_query else {},
        "query_aliases": search_query.aliases if q and search_query else {},
        "selected_department": selected_department,
        "selected_folder": selected_folder,
        "selected_doc_type": selected_doc_type,
        "has_active_filters": any(
            [q, doc_type_id, department_id, folder_id, counterparty, amount_min, amount_max, status, date_from, date_to]
        ),
    }

    return render(request, "dms/document_list.html", context)



# =========================================================
# DOCUMENT UPLOAD
# =========================================================
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.db import transaction

from dms.forms import DocumentUploadForm
from dms.models import DocumentType, DocumentAccess, DocumentActivity
from dms.services.text_extractor import extract_text_from_file
from dms.services.embedding import build_embedding
from dms.services.ai_parser import parse_document
from dms.services.document_metadata import extract_candidate_dates, extract_doc_type
from dms.services.folders import (
    get_or_create_folder_tree,
    attach_document_to_folder,
)
from dms.services.preservation import (
    calculate_file_sha256,
    calculate_sha256,
    detect_format_risk,
    detect_mime_type,
)
from dms.utils import get_allowed_departments


@login_required
@transaction.atomic
def document_upload(request):
    user = request.user

    if user.role != "ADMIN" and not user.department_id:
        return HttpResponseForbidden("У вас не указан отдел")

    if request.method == "POST":
        post_data = request.POST.copy()
        if user.role != "ADMIN" and user.department_id and not post_data.get("department"):
            post_data["department"] = str(user.department_id)

        form = DocumentUploadForm(
            post_data,
            request.FILES,
            user=user,
        )

        if not form.is_valid():
            return render(
                request,
                "dms/document_form.html",
                build_document_form_context(
                    form=form,
                    user=user,
                    mode="create",
                ),
            )

        department = form.cleaned_data["department"]

        if user.role != "ADMIN":
            allowed = get_allowed_departments(user)
            if not allowed.filter(id=department.id).exists():
                return HttpResponseForbidden("Нельзя загрузить в этот отдел")

        folder = form.cleaned_data.get("folder")
        subfolder = form.cleaned_data.get("subfolder")
        if subfolder:
            folder = subfolder

        doc, version = create_document_from_uploaded_file(
            uploaded_file=form.cleaned_data["file"],
            department=department,
            folder=folder,
            folder_name=form.cleaned_data.get("new_folder") or "",
            subfolder_name=form.cleaned_data.get("new_subfolder") or "",
            title=form.cleaned_data["title"],
            description=form.cleaned_data.get("description") or "",
            doc_type=form.cleaned_data.get("doc_type"),
            doc_date=form.cleaned_data.get("doc_date"),
            language=form.cleaned_data.get("language") or Document.Language.UNKNOWN,
            document_author=form.cleaned_data.get("document_author") or "",
            status=form.cleaned_data.get("status") or Document.Status.DRAFT,
            retention_category=form.cleaned_data.get("retention_category") or "",
            retention_until=form.cleaned_data.get("retention_until"),
            legal_hold=form.cleaned_data.get("legal_hold") or False,
            source_system=form.cleaned_data.get("source_system") or "manual_upload",
            uploaded_by=user,
            request=request,
            run_ai=True,
            parser=parse_document,
            text_extractor=extract_text_from_file,
            indexer=index_document,
        )

        # =================================================
        # 6. ДОСТУПЫ
        # =================================================
        for dept in form.cleaned_data.get("access_departments", []):
            DocumentAccess.objects.get_or_create(
                document=doc,
                department=dept,
                defaults={"granted_by": user},
            )

        return redirect("dms:document_list")

    # =====================================================
    # GET
    # =====================================================
    form = DocumentUploadForm(user=user)
    return render(
        request,
        "dms/document_form.html",
        build_document_form_context(
            form=form,
            user=user,
            mode="create",
        ),
    )


@login_required
def document_import(request):
    user = request.user

    if user.role != "ADMIN" and not user.department_id:
        return HttpResponseForbidden("У вас не указан отдел")

    if request.method == "POST":
        post_data = request.POST.copy()
        if user.role != "ADMIN" and user.department_id and not post_data.get("department"):
            post_data["department"] = str(user.department_id)

        form = ImportBatchForm(post_data, request.FILES, user=user)
        if form.is_valid():
            department = form.cleaned_data["department"]
            if not get_allowed_departments(user).filter(id=department.id).exists():
                return HttpResponseForbidden("Нельзя импортировать в этот отдел")

            folder = form.cleaned_data.get("folder")
            if form.cleaned_data.get("new_folder"):
                folder = get_or_create_folder_tree(
                    department=department,
                    folder_name=form.cleaned_data["new_folder"],
                )

            files = form.cleaned_data["files"]
            batch = create_import_batch(
                organization=department.organization,
                department=department,
                folder=folder,
                created_by=user,
                total_files=len(files),
                request=request,
            )
            import_uploaded_files(
                batch=batch,
                files=files,
                created_by=user,
                request=request,
            )
            messages.success(request, "Импорт завершен")
            return redirect("dms:import_batch_detail", pk=batch.id)
    else:
        form = ImportBatchForm(user=user)

    recent_batches = (
        ImportBatch.objects
        .filter(organization__in=get_user_organizations(user))
        .select_related("department", "folder", "created_by")
        .order_by("-created_at")[:10]
    )
    return render(
        request,
        "dms/document_import.html",
        {
            "form": form,
            "recent_batches": recent_batches,
        },
    )


@login_required
def import_batch_detail(request, pk):
    batch = get_object_or_404(
        ImportBatch.objects.select_related("organization", "department", "folder", "created_by"),
        pk=pk,
        organization__in=get_user_organizations(request.user),
    )
    if not get_allowed_departments(request.user).filter(id=batch.department_id).exists():
        return HttpResponseForbidden("Нет доступа к партии импорта")

    files = (
        batch.files
        .select_related("document", "duplicate_of")
        .order_by("id")
    )
    return render(
        request,
        "dms/import_batch_detail.html",
        {
            "batch": batch,
            "files": files,
        },
    )

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.loader import render_to_string

from dms.models import Folder, Department


from django.shortcuts import render
from dms.models import Folder

@login_required
def folders_by_department(request):
    allowed_departments = get_allowed_departments(request.user)
    form = DepartmentSelectionForm(
        request.GET or None,
        allowed_departments=allowed_departments,
    )
    if not form.is_valid():
        return HttpResponseBadRequest("Некорректный отдел.")

    folders = (
        Folder.objects
        .filter(
            department_id=form.cleaned_data["department"],
            parent__isnull=True,
        )
        .order_by("tree_id", "lft")
    )

    return render(
        request,
        "dms/folder_options.html",
        {"folders": folders},
    )

@login_required
def subfolders_by_parent(request):
    allowed_departments = get_allowed_departments(request.user)
    form = ParentFolderSelectionForm(
        request.GET or None,
        allowed_departments=allowed_departments,
    )
    if not form.is_valid():
        return HttpResponseBadRequest("Некорректная родительская папка.")

    parent = Folder.objects.filter(id=form.cleaned_data["folder"]).first()
    subfolders = []
    if parent:
        subfolders = (
            Folder.objects
            .filter(parent=parent)
            .order_by("tree_id", "lft")
        )

    return render(
        request,
        "dms/subfolder_options.html",
        {"subfolders": subfolders},
    )


# =========================================================
# DOCUMENT EDIT
# =========================================================
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required

from dms.models import DocumentActivity
from dms.services.text_extractor import extract_text_from_file
from dms.services.embedding import build_embedding
from dms.services.vector_store import upsert_document
from dms.utils import get_allowed_departments, get_allowed_documents


@login_required
def document_edit(request, pk):
    user = request.user

    # ============================
    # ДОСТУП К ДОКУМЕНТУ
    # ============================
    doc = get_object_or_404(
        get_allowed_documents(user),
        pk=pk
    )

    allowed_departments = get_allowed_departments(user)

    if doc.department not in allowed_departments:
        return HttpResponseForbidden("Нет доступа")

    # ============================
    # POST
    # ============================
    if request.method == "POST":
        form = DocumentUploadForm(
            request.POST,
            request.FILES,
            instance=doc,
            user=user
        )

        if not form.is_valid():
            return render(
                request,
                "dms/document_form.html",
                build_document_form_context(
                    form=form,
                    user=user,
                    doc=doc,
                    versions=doc.versions.select_related(
                        "uploaded_by",
                        "doc_type",
                        "folder",
                    ),
                    mode="edit",
                ),
            )

        original_doc = get_object_or_404(get_allowed_documents(user), pk=doc.pk)
        updated = form.save(commit=False)
        updated.organization = updated.department.organization

        # ---- защита отдела
        if updated.department not in allowed_departments:
            return HttpResponseForbidden("Недопустимый отдел")

        folder = get_or_create_folder_tree(
            department=updated.department,
            parent_folder=form.cleaned_data.get("folder"),
            folder_name=form.cleaned_data.get("new_folder"),
            subfolder_name=form.cleaned_data.get("new_subfolder"),
        )

        if folder:
            updated.folder = folder

        # ============================
        # ФАЙЛ МОГ ИЗМЕНИТЬСЯ
        # ============================
        if "file" in request.FILES:
            updated.save()
            attach_document_to_folder(
                document=updated,
                folder=updated.folder,
            )
            updated.extracted_text = extract_text_from_file(updated.file.path) or ""
            populate_preservation_metadata(updated, form.cleaned_data.get("file"))
            updated.save(
                update_fields=[
                    "organization",
                    "department",
                    "folder",
                    "title",
                    "doc_type",
                    "language",
                    "document_author",
                    "status",
                    "doc_date",
                    "retention_category",
                    "retention_until",
                    "legal_hold",
                    "source_system",
                    "description",
                    "file",
                    "extracted_text",
                    "source_file_name",
                    "mime_type",
                    "checksum_sha256",
                    "format_risk_level",
                ]
            )
        else:
            populate_preservation_metadata(updated)
            updated.save()
            attach_document_to_folder(
                document=updated,
                folder=updated.folder,
            )

        # ============================
        # СОХРАНЕНИЕ В БД
        # ============================
        version = None
        snapshot_changed = document_snapshot_changed(original_doc, updated)
        if snapshot_changed:
            version = updated.create_version(uploaded_by=user)

        # ============================
        # ОБНОВЛЕНИЕ EMBEDDING / QDRANT
        # ============================
        index_document(updated)

        # ============================
        # ЛОГ
        # ============================
        DocumentActivity.objects.create(
            user=user,
            document=updated,
            action=DocumentActivity.ACTION_UPDATED,
        )
        record_audit_event(
            event_type=AuditEvent.EventType.DOCUMENT_UPDATED,
            request=request,
            document=updated,
            document_version=version,
            metadata={
                "version_created": snapshot_changed,
                "previous_status": original_doc.status,
                "new_status": updated.status,
                "file_changed": "file" in request.FILES,
            },
        )

        return redirect("dms:document_list")

    # ============================
    # GET
    # ============================
    form = DocumentUploadForm(instance=doc, user=user)
    versions = doc.versions.select_related("uploaded_by", "doc_type", "folder")

    return render(
        request,
        "dms/document_form.html",
        build_document_form_context(
            form=form,
            user=user,
            doc=doc,
            versions=versions,
            mode="edit",
        ),
    )



# =========================================================
# SAFE VIEW / DOWNLOAD (с логами)
# =========================================================
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required

from dms.utils import get_allowed_documents
from dms.models import DocumentActivity


@login_required
def document_view(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related(
            "department",
            "doc_type",
        ),
        pk=pk,
    )

    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")

    if not doc.file:
        raise Http404("Файл не найден")

    # ---- ЛОГ ----
    DocumentActivity.objects.create(
        user=request.user,
        document=doc,
        action=DocumentActivity.ACTION_VIEWED,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_VIEWED,
        request=request,
        document=doc,
        metadata={"surface": "file_view"},
    )

    return protected_file_response(doc.file, as_attachment=False)


def get_document_preview_kind(file_name: str) -> str:
    ext = os.path.splitext((file_name or "").lower())[1]
    if ext == ".pdf":
        return "pdf"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        return "image"
    return "unsupported"


def build_document_ai_summary(doc) -> str:
    if doc.description:
        return doc.description.strip()

    text = " ".join(
        filter(
            None,
            [
                doc.title,
                doc.extracted_text[:1200] if doc.extracted_text else "",
            ],
        )
    ).strip()
    if not text:
        return ""

    compact = " ".join(text.split())
    if len(compact) > 320:
        compact = compact[:320].rstrip(" ,;:") + "..."
    return compact


def get_similar_documents_for_user(doc, user, limit: int = 4):
    queryset = get_allowed_documents(user).filter().exclude(id=doc.id)

    if doc.doc_type_id:
        queryset = queryset.filter(doc_type_id=doc.doc_type_id)
    elif doc.department_id:
        queryset = queryset.filter(department_id=doc.department_id)

    queryset = queryset.select_related("department", "folder", "doc_type")

    title_tokens = [
        token.strip().lower()
        for token in re.split(r"\W+", doc.title or "")
        if len(token.strip()) >= 4
    ]
    if title_tokens:
        q = Q()
        for token in title_tokens[:4]:
            q |= Q(title__icontains=token) | Q(description__icontains=token)
        queryset = queryset.filter(q)

    return list(queryset.order_by("-doc_date", "-id")[:limit])


def can_validate_ai_fields(user, doc) -> bool:
    if user.role == "ADMIN":
        return True
    if doc.uploaded_by_id == user.id:
        return True
    return bool(user.department_id and doc.department_id == user.department_id)


@login_required
def document_detail(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user)
        .select_related("department", "doc_type", "folder", "uploaded_by")
        .prefetch_related(
            "versions__uploaded_by",
            "versions__doc_type",
            "accesses__department",
            "accesses__granted_by",
            "activities__user",
            "outgoing_relations__to_document",
            "incoming_relations__from_document",
        ),
        pk=pk,
    )

    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")

    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_VIEWED,
        request=request,
        document=doc,
        metadata={"surface": "document_detail"},
    )

    doc.can_manage_access = (
        request.user.role == "ADMIN"
        or doc.uploaded_by_id == request.user.id
        or doc.department_id == request.user.department_id
    )

    versions = doc.versions.all()
    accesses = doc.accesses.all()
    activities = doc.activities.all()[:12]
    visible_relations = get_visible_document_relations(user=request.user, document=doc)
    outgoing_relations = visible_relations.outgoing
    incoming_relations = visible_relations.incoming
    can_manage_relations = can_manage_document_relations(user=request.user, document=doc)
    allowed_queryset = get_allowed_documents(request.user)
    relation_graph = build_document_relation_graph(user=request.user, document=doc)
    relation_suggestions = suggest_document_relations(
        user=request.user,
        document=doc,
        allowed_queryset=allowed_queryset,
    )
    superseded_candidates = get_superseded_candidates(doc, allowed_queryset)
    retention_hint = build_retention_assistant(doc)
    card_quality = build_card_quality(doc)
    folder_path = _folder_path(doc.folder) if doc.folder else "Без папки"
    preview_kind = get_document_preview_kind(doc.file.name if doc.file else "")
    ai_summary = build_document_ai_summary(doc)
    similar_documents = get_similar_documents_for_user(doc, request.user)
    latest_processing_job = (
        doc.processing_jobs
        .prefetch_related("fields")
        .order_by("-created_at")
        .first()
    )
    active_workflow = get_active_workflow(doc)
    workflow_actions = (
        doc.workflow_actions
        .select_related("actor", "step_template", "instance")
        .order_by("-created_at", "-id")[:12]
    )
    workflow_start_form = None
    if active_workflow is None and can_start_workflow(request.user, doc):
        candidate_form = WorkflowStartForm(user=request.user, document=doc)
        if candidate_form.fields["template"].queryset.exists():
            workflow_start_form = candidate_form
    recent_exchanges = (
        doc.exchanges
        .select_related("counterparty", "counterparty_contact", "sent_by", "received_by")
        .prefetch_related("events", "messages")
        .order_by("-created_at")[:8]
    )
    counterparty_exchange_form = None
    if can_send_document_exchange(request.user, doc):
        counterparty_exchange_form = CounterpartyExchangeForm(user=request.user, document=doc)
    new_exchange_url = request.session.pop(f"counterparty_exchange_url:{doc.pk}", "")

    return render(
        request,
        "dms/document_detail.html",
        {
            "doc": doc,
            "versions": versions,
            "accesses": accesses,
            "activities": activities,
            "outgoing_relations": outgoing_relations,
            "incoming_relations": incoming_relations,
            "relation_form": (
                DocumentRelationForm(user=request.user, document=doc)
                if can_manage_relations
                else None
            ),
            "can_manage_relations": can_manage_relations,
            "relation_suggestions": relation_suggestions,
            "relation_graph": relation_graph,
            "superseded_candidates": superseded_candidates,
            "retention_hint": retention_hint,
            "card_quality": card_quality,
            "folder_path": folder_path,
            "preview_kind": preview_kind,
            "ai_summary": ai_summary,
            "similar_documents": similar_documents,
            "latest_processing_job": latest_processing_job,
            "can_validate_ai": can_validate_ai_fields(request.user, doc),
            "active_workflow": active_workflow,
            "workflow_actions": workflow_actions,
            "workflow_start_form": workflow_start_form,
            "workflow_action_form": WorkflowActionForm(),
            "can_act_on_active_workflow": (
                can_act_on_workflow(request.user, active_workflow)
                if active_workflow
                else False
            ),
            "recent_exchanges": recent_exchanges,
            "counterparty_exchange_form": counterparty_exchange_form,
            "new_exchange_url": new_exchange_url,
        },
    )


@login_required
@require_POST
def document_relation_add(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related("organization", "department", "uploaded_by"),
        pk=pk,
    )
    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("РќРµС‚ РґРѕСЃС‚СѓРїР° Рє РґРѕРєСѓРјРµРЅС‚Сѓ")
    if not can_manage_document_relations(user=request.user, document=doc):
        return HttpResponseForbidden("РќРµС‚ РїСЂР°РІ РЅР° СѓРїСЂР°РІР»РµРЅРёРµ СЃРІСЏР·СЏРјРё")

    form = DocumentRelationForm(request.POST, user=request.user, document=doc)
    if not form.is_valid():
        messages.error(request, "Could not create relation. Check the related document and relation type.")
        return redirect("dms:document_detail", pk=doc.pk)

    related_document = form.cleaned_data["to_document"]
    try:
        _relation, created = create_document_relation(
            user=request.user,
            from_document=doc,
            to_document=related_document,
            relation_type=form.cleaned_data["relation_type"],
            request=request,
        )
    except PermissionDenied:
        return HttpResponseForbidden("РќРµС‚ РїСЂР°РІ РЅР° СЃРѕР·РґР°РЅРёРµ СЌС‚РѕР№ СЃРІСЏР·Рё")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("dms:document_detail", pk=doc.pk)

    if created:
        messages.success(request, "Document relation created.")
    else:
        messages.info(request, "This document relation already exists.")
    return redirect("dms:document_detail", pk=doc.pk)


@login_required
@require_POST
def document_relation_delete(request, pk, relation_pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related("organization", "department", "uploaded_by"),
        pk=pk,
    )
    relation = get_object_or_404(
        DocumentRelation.objects.select_related(
            "from_document",
            "from_document__organization",
            "from_document__department",
            "to_document",
            "to_document__organization",
            "to_document__department",
        ),
        pk=relation_pk,
    )
    try:
        delete_document_relation(
            user=request.user,
            relation=relation,
            current_document=doc,
            request=request,
        )
    except PermissionDenied:
        return HttpResponseForbidden("РќРµС‚ РїСЂР°РІ РЅР° СѓРґР°Р»РµРЅРёРµ СЌС‚РѕР№ СЃРІСЏР·Рё")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("dms:document_detail", pk=doc.pk)

    messages.success(request, "Document relation deleted.")
    return redirect("dms:document_detail", pk=doc.pk)


@login_required
def document_evidence_export(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related("organization", "department", "uploaded_by"),
        pk=pk,
    )
    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("РќРµС‚ РґРѕСЃС‚СѓРїР° Рє РґРѕРєСѓРјРµРЅС‚Сѓ")

    package = build_document_evidence_package(document=doc, exported_by=request.user)
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_DOWNLOADED,
        request=request,
        user=request.user,
        document=doc,
        organization=doc.organization,
        metadata={
            "evidence_exported": True,
            "evidence_event_name": "evidence.exported",
            "evidence_schema": package["schema"]["name"],
            "evidence_schema_version": package["schema"]["version"],
            "evidence_format": "json",
        },
    )
    record_usage_event(
        event_type=UsageEvent.EventType.EVIDENCE_EXPORTED,
        user=request.user,
        document=doc,
        source="evidence_export",
        metadata={
            "evidence_schema": package["schema"]["name"],
            "evidence_schema_version": package["schema"]["version"],
            "evidence_format": "json",
        },
    )
    response = JsonResponse(package, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = f'attachment; filename="document-{doc.id}-evidence.json"'
    return response


@login_required
def document_evidence_report(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related("organization", "department", "uploaded_by"),
        pk=pk,
    )
    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")

    package = build_document_evidence_package(document=doc, exported_by=request.user)
    report_context = build_evidence_report_context(package)
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_DOWNLOADED,
        request=request,
        user=request.user,
        document=doc,
        organization=doc.organization,
        metadata={
            "evidence_exported": True,
            "evidence_event_name": "evidence.report_viewed",
            "evidence_schema": package["schema"]["name"],
            "evidence_schema_version": package["schema"]["version"],
            "evidence_format": "html",
            "report_checksum_sha256": report_context["report_checksum_sha256"],
        },
    )
    record_usage_event(
        event_type=UsageEvent.EventType.EVIDENCE_EXPORTED,
        user=request.user,
        document=doc,
        source="evidence_report",
        metadata={
            "evidence_schema": package["schema"]["name"],
            "evidence_schema_version": package["schema"]["version"],
            "evidence_format": "html",
        },
    )
    response = render(request, "dms/evidence_report.html", report_context)
    response["Content-Disposition"] = f'inline; filename="document-{doc.id}-evidence-report.html"'
    return response


@login_required
@require_POST
def document_workflow_start(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related("organization", "department", "uploaded_by"),
        pk=pk,
    )
    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")
    if not can_start_workflow(request.user, doc):
        return HttpResponseForbidden("Нет прав на запуск workflow")

    form = WorkflowStartForm(request.POST, user=request.user, document=doc)
    if not form.is_valid():
        messages.error(request, "Не удалось запустить workflow: проверьте шаблон.")
        return redirect("dms:document_detail", pk=doc.pk)

    try:
        start_workflow(
            document=doc,
            template=form.cleaned_data["template"],
            user=request.user,
            request=request,
            comment=form.cleaned_data.get("comment", ""),
        )
    except WorkflowPermissionError:
        return HttpResponseForbidden("Нет прав на запуск workflow")
    except WorkflowError as exc:
        messages.error(request, f"Не удалось запустить workflow: {exc}")
    else:
        messages.success(request, "Workflow запущен.")
    return redirect("dms:document_detail", pk=doc.pk)


@login_required
@require_POST
def document_workflow_action(request, pk, instance_pk, action):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related("organization", "department"),
        pk=pk,
    )
    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")

    instance = get_object_or_404(
        WorkflowInstance.objects.select_related(
            "document",
            "template",
            "current_step_template",
        ),
        pk=instance_pk,
        document=doc,
        organization__in=get_user_organizations(request.user),
    )

    form = WorkflowActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Не удалось сохранить действие workflow.")
        return redirect("dms:document_detail", pk=doc.pk)

    comment = form.cleaned_data.get("comment", "")
    actions = {
        "approve": approve_workflow,
        "reject": reject_workflow,
        "request-changes": request_workflow_changes,
        "comment": comment_workflow,
    }
    handler = actions.get(action)
    if handler is None:
        return HttpResponseBadRequest("Unknown workflow action")

    try:
        handler(
            instance=instance,
            user=request.user,
            request=request,
            comment=comment,
        )
    except WorkflowPermissionError:
        return HttpResponseForbidden("Нет прав на действие workflow")
    except WorkflowError as exc:
        messages.error(request, f"Workflow action failed: {exc}")
    else:
        messages.success(request, "Workflow action saved.")
    return redirect("dms:document_detail", pk=doc.pk)


@login_required
@require_POST
def document_exchange_send(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related("organization", "department", "uploaded_by"),
        pk=pk,
    )
    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")
    if not can_send_document_exchange(request.user, doc):
        return HttpResponseForbidden("Нет прав на отправку документа контрагенту")

    form = CounterpartyExchangeForm(request.POST, user=request.user, document=doc)
    if not form.is_valid():
        messages.error(request, "Не удалось создать exchange: проверьте контрагента и срок действия.")
        return redirect("dms:document_detail", pk=doc.pk)

    counterparty = form.cleaned_data.get("counterparty")
    if counterparty is None:
        counterparty, created = Counterparty.objects.get_or_create(
            organization=doc.organization,
            name=form.cleaned_data["new_counterparty_name"],
            defaults={
                "email": form.cleaned_data.get("new_counterparty_email", ""),
                "contact_name": form.cleaned_data.get("new_contact_name", ""),
                "created_by": request.user,
            },
        )
        updates = []
        if not created:
            email = form.cleaned_data.get("new_counterparty_email", "")
            contact_name = form.cleaned_data.get("new_contact_name", "")
            if email and not counterparty.email:
                counterparty.email = email
                updates.append("email")
            if contact_name and not counterparty.contact_name:
                counterparty.contact_name = contact_name
                updates.append("contact_name")
            if updates:
                counterparty.save(update_fields=[*updates, "updated_at"])

    expires_days = form.cleaned_data.get("expires_days") or 14
    expires_at = timezone.now() + timedelta(days=expires_days)
    try:
        created_exchange = create_document_exchange(
            document=doc,
            counterparty=counterparty,
            user=request.user,
            request=request,
            message=form.cleaned_data.get("message", ""),
            expires_at=expires_at,
            business_document_type=form.cleaned_data.get("business_document_type", ""),
            counterparty_contact=form.cleaned_data.get("counterparty_contact"),
            contact_name=form.cleaned_data.get("new_contact_name", ""),
            contact_email=form.cleaned_data.get("new_contact_email") or form.cleaned_data.get("new_counterparty_email", ""),
        )
    except ExchangePermissionError:
        return HttpResponseForbidden("Нет прав на отправку документа контрагенту")
    except ExchangeError as exc:
        messages.error(request, f"Не удалось создать exchange: {exc}")
    else:
        request.session[f"counterparty_exchange_url:{doc.pk}"] = request.build_absolute_uri(
            created_exchange.portal_path()
        )
        messages.success(request, "Counterparty exchange создан. Ссылка показана в карточке документа.")
    return redirect("dms:document_detail", pk=doc.pk)


def _get_or_create_counterparty_from_form(form, organization, user):
    counterparty = form.cleaned_data.get("counterparty")
    if counterparty is not None:
        return counterparty

    counterparty, created = Counterparty.objects.get_or_create(
        organization=organization,
        name=form.cleaned_data["new_counterparty_name"],
        defaults={
            "email": form.cleaned_data.get("new_counterparty_email", ""),
            "contact_name": form.cleaned_data.get("new_contact_name", ""),
            "created_by": user,
        },
    )
    updates = []
    if not created:
        email = form.cleaned_data.get("new_counterparty_email", "")
        contact_name = form.cleaned_data.get("new_contact_name", "")
        if email and not counterparty.email:
            counterparty.email = email
            updates.append("email")
        if contact_name and not counterparty.contact_name:
            counterparty.contact_name = contact_name
            updates.append("contact_name")
        if updates:
            counterparty.save(update_fields=[*updates, "updated_at"])
    return counterparty


@login_required
def exchange_list(request):
    form = ExchangeListFilterForm(request.GET or None, user=request.user)
    allowed_documents = get_allowed_documents(request.user).values("id")
    exchanges = (
        DocumentExchange.objects
        .filter(
            organization__in=get_user_organizations(request.user),
            document_id__in=allowed_documents,
        )
        .select_related("document", "counterparty", "counterparty_contact", "sent_by", "received_by")
        .prefetch_related("messages")
        .order_by("-created_at")
    )

    if form.is_valid():
        direction = form.cleaned_data.get("direction")
        status = form.cleaned_data.get("status")
        counterparty_id = form.cleaned_data.get("counterparty")
        if direction:
            exchanges = exchanges.filter(direction=direction)
        if status:
            exchanges = exchanges.filter(status=status)
        if counterparty_id:
            exchanges = exchanges.filter(counterparty_id=counterparty_id)
    else:
        messages.error(request, "Invalid exchange filters.")

    counterparties = Counterparty.objects.filter(
        organization__in=get_user_organizations(request.user),
        document_exchanges__document_id__in=allowed_documents,
    ).distinct().order_by("name")

    return render(
        request,
        "dms/exchange_list.html",
        {
            "form": form,
            "exchanges": exchanges[:100],
            "counterparties": counterparties,
            "direction": request.GET.get("direction", ""),
            "status": request.GET.get("status", ""),
            "counterparty": request.GET.get("counterparty", ""),
        },
    )


def _allowed_exchange_queryset(user):
    allowed_documents = get_allowed_documents(user).values("id")
    return (
        DocumentExchange.objects
        .filter(
            organization__in=get_user_organizations(user),
            document_id__in=allowed_documents,
        )
        .select_related(
            "organization",
            "document",
            "document__department",
            "counterparty",
            "counterparty_contact",
            "sent_by",
            "received_by",
        )
    )


@login_required
def exchange_detail(request, exchange_id):
    exchange = get_object_or_404(_allowed_exchange_queryset(request.user), pk=exchange_id)
    if not user_can_access_document(request.user, exchange.document):
        return HttpResponseForbidden("No access to exchange")

    new_exchange_url = request.session.pop(f"exchange_portal_url:{exchange.pk}", "")
    events = exchange.events.order_by("-created_at", "-id")[:50]
    exchange_messages = exchange.messages.select_related("user", "counterparty_contact").order_by("created_at", "id")[:50]
    can_manage_exchange = (
        exchange.direction == DocumentExchange.Direction.OUTGOING
        and can_send_document_exchange(request.user, exchange.document)
    )
    return render(
        request,
        "dms/exchange_detail.html",
        {
            "exchange": exchange,
            "doc": exchange.document,
            "events": events,
            "exchange_messages": exchange_messages,
            "message_form": ExchangeMessageForm(),
            "resend_form": ExchangeLinkResendForm(initial={"expires_days": 14}),
            "new_exchange_url": new_exchange_url,
            "can_manage_exchange": can_manage_exchange,
        },
    )


@login_required
@require_POST
def exchange_revoke(request, exchange_id):
    exchange = get_object_or_404(_allowed_exchange_queryset(request.user), pk=exchange_id)
    if not user_can_access_document(request.user, exchange.document):
        return HttpResponseForbidden("No access to exchange")
    try:
        revoke_exchange_link(
            exchange=exchange,
            user=request.user,
            request=request,
            comment=request.POST.get("comment", ""),
        )
    except ExchangePermissionError:
        return HttpResponseForbidden("No permission to revoke exchange")
    except ExchangeError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Exchange link revoked.")
    return redirect("dms:exchange_detail", exchange_id=exchange.id)


@login_required
@require_POST
def exchange_resend(request, exchange_id):
    exchange = get_object_or_404(_allowed_exchange_queryset(request.user), pk=exchange_id)
    if not user_can_access_document(request.user, exchange.document):
        return HttpResponseForbidden("No access to exchange")
    form = ExchangeLinkResendForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Could not resend exchange link.")
        return redirect("dms:exchange_detail", exchange_id=exchange.id)

    expires_at = timezone.now() + timedelta(days=form.cleaned_data["expires_days"])
    try:
        created_exchange = reissue_exchange_link(
            exchange=exchange,
            user=request.user,
            request=request,
            expires_at=expires_at,
            message=form.cleaned_data.get("message", ""),
        )
    except ExchangePermissionError:
        return HttpResponseForbidden("No permission to resend exchange")
    except ExchangeError as exc:
        messages.error(request, str(exc))
    else:
        request.session[f"exchange_portal_url:{exchange.pk}"] = request.build_absolute_uri(
            created_exchange.portal_path()
        )
        messages.success(request, "Exchange link resent.")
    return redirect("dms:exchange_detail", exchange_id=exchange.id)


@login_required
def incoming_exchange_create(request):
    if request.method == "POST":
        form = IncomingExchangeForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            department = form.cleaned_data["department"]
            if not get_allowed_departments(request.user).filter(id=department.id).exists():
                return HttpResponseForbidden("Нет прав на прием документов в этот отдел")
            try:
                counterparty = _get_or_create_counterparty_from_form(
                    form,
                    department.organization,
                    request.user,
                )
                exchange, document = create_incoming_document_exchange(
                    uploaded_file=form.cleaned_data["file"],
                    department=department,
                    folder=form.cleaned_data.get("folder"),
                    counterparty=counterparty,
                    user=request.user,
                    request=request,
                    title=form.cleaned_data.get("title", ""),
                    description=form.cleaned_data.get("description", ""),
                    business_document_type=form.cleaned_data.get("business_document_type", ""),
                    message=form.cleaned_data.get("message", ""),
                    counterparty_contact=form.cleaned_data.get("counterparty_contact"),
                    contact_name=form.cleaned_data.get("new_contact_name", ""),
                    contact_email=form.cleaned_data.get("new_contact_email") or form.cleaned_data.get("new_counterparty_email", ""),
                )
            except ExchangePermissionError:
                return HttpResponseForbidden("Нет прав на прием документов в этот отдел")
            except ExchangeError as exc:
                messages.error(request, f"Could not receive incoming document: {exc}")
            else:
                messages.success(request, "Incoming B2B document received.")
                return redirect("dms:document_detail", pk=document.pk)
    else:
        form = IncomingExchangeForm(user=request.user)

    return render(
        request,
        "dms/incoming_exchange_form.html",
        {
            "form": form,
        },
    )


@login_required
@require_POST
def exchange_message_create(request, exchange_id):
    allowed_documents = get_allowed_documents(request.user).values("id")
    exchange = get_object_or_404(
        DocumentExchange.objects.select_related("document", "counterparty").filter(
            organization__in=get_user_organizations(request.user),
            document_id__in=allowed_documents,
        ),
        pk=exchange_id,
    )
    if not user_can_access_document(request.user, exchange.document):
        return HttpResponseForbidden("РќРµС‚ РґРѕСЃС‚СѓРїР° Рє exchange")

    form = ExchangeMessageForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Could not save exchange message.")
        return redirect("dms:document_detail", pk=exchange.document_id)

    try:
        record_exchange_message(
            exchange=exchange,
            author_type="INTERNAL",
            user=request.user,
            request=request,
            body=form.cleaned_data["body"],
            source_event_type=ExchangeEvent.EventType.COMMENTED,
        )
    except ExchangePermissionError:
        return HttpResponseForbidden("РќРµС‚ РїСЂР°РІ РЅР° СЃРѕРѕР±С‰РµРЅРёРµ РІ exchange")
    except ExchangeError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Exchange message saved.")
    if request.POST.get("next") == "exchange_detail":
        return redirect("dms:exchange_detail", exchange_id=exchange.id)
    return redirect("dms:document_detail", pk=exchange.document_id)


def _get_exchange_by_token_or_404(token: str) -> DocumentExchange:
    exchange = resolve_exchange_token(token)
    if exchange is None:
        raise Http404("Exchange not found")
    return exchange


def counterparty_portal(request, token):
    exchange = _get_exchange_by_token_or_404(token)
    if is_exchange_expired(exchange):
        exchange = expire_exchange(exchange=exchange, request=request)
    elif not exchange.is_terminal:
        exchange = mark_exchange_opened(exchange=exchange, request=request)

    is_revoked = exchange.status == DocumentExchange.Status.REVOKED
    is_expired = exchange.status == DocumentExchange.Status.EXPIRED
    return render(
        request,
        "dms/counterparty_portal.html",
        {
            "exchange": exchange,
            "doc": exchange.document,
            "events": exchange.events.all()[:12],
            "exchange_messages": exchange.messages.select_related("user", "counterparty_contact")[:20],
            "form": ExternalExchangeActionForm(),
            "token": token,
            "is_closed": exchange.is_terminal,
            "is_expired": is_expired,
            "is_revoked": is_revoked,
            "is_link_unavailable": is_expired or is_revoked,
        },
    )


@require_POST
def counterparty_portal_action(request, token, action):
    exchange = _get_exchange_by_token_or_404(token)
    if is_exchange_expired(exchange):
        expire_exchange(exchange=exchange, request=request)
        messages.error(request, "This exchange link has expired.")
        return redirect("dms:counterparty_portal", token=token)
    if exchange.status == DocumentExchange.Status.REVOKED:
        messages.error(request, "This exchange link has been revoked.")
        return redirect("dms:counterparty_portal", token=token)

    form = ExternalExchangeActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Could not save portal action.")
        return redirect("dms:counterparty_portal", token=token)

    comment = form.cleaned_data.get("comment", "")
    try:
        if action == "accept":
            accept_exchange(exchange=exchange, request=request, comment=comment)
            messages.success(request, "Document accepted.")
        elif action == "reject":
            reject_exchange(exchange=exchange, request=request, comment=comment)
            messages.success(request, "Document rejected.")
        elif action == "comment":
            comment_exchange(exchange=exchange, request=request, comment=comment)
            messages.success(request, "Comment saved.")
        else:
            return HttpResponseBadRequest("Unknown portal action")
    except ExchangeError as exc:
        messages.error(request, str(exc))
    return redirect("dms:counterparty_portal", token=token)


def counterparty_portal_download(request, token):
    exchange = _get_exchange_by_token_or_404(token)
    if is_exchange_expired(exchange):
        expire_exchange(exchange=exchange, request=request)
        raise Http404("Exchange expired")
    if exchange.status == DocumentExchange.Status.REVOKED:
        raise Http404("Exchange not available")
    if not exchange.document.file:
        raise Http404("Document file not found")

    if exchange.status == DocumentExchange.Status.SENT:
        exchange = mark_exchange_opened(exchange=exchange, request=request)
    record_exchange_download(exchange=exchange, request=request)
    return protected_file_response(exchange.document.file, as_attachment=True)


@login_required
def notification_list(request):
    notifications = (
        Notification.objects
        .filter(
            recipient=request.user,
            organization__in=get_user_organizations(request.user),
        )
        .select_related(
            "actor",
            "related_document",
            "related_document__department",
            "related_exchange",
            "related_exchange__document",
            "related_exchange__counterparty",
        )
        .order_by("-created_at", "-id")[:100]
    )

    items = []
    for notification in notifications:
        document_url = ""
        exchange_url = ""
        if notification.related_document_id and user_can_access_document(request.user, notification.related_document):
            document_url = reverse("dms:document_detail", args=[notification.related_document_id])
        if (
            notification.related_exchange_id
            and notification.related_exchange.document_id
            and user_can_access_document(request.user, notification.related_exchange.document)
        ):
            exchange_url = reverse("dms:exchange_detail", args=[notification.related_exchange_id])
        items.append(
            {
                "notification": notification,
                "document_url": document_url,
                "exchange_url": exchange_url,
            }
        )

    return render(
        request,
        "dms/notification_list.html",
        {
            "items": items,
        },
    )


@login_required
@require_POST
def notification_mark_read(request, pk):
    notification = get_object_or_404(
        Notification.objects.filter(
            recipient=request.user,
            organization__in=get_user_organizations(request.user),
        ),
        pk=pk,
    )
    notification.mark_read()
    return redirect("dms:notification_list")


@login_required
def document_ai_review(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user)
        .select_related("organization", "department", "doc_type", "uploaded_by"),
        pk=pk,
    )

    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")
    if not can_validate_ai_fields(request.user, doc):
        return HttpResponseForbidden("Нет прав на проверку AI-полей")

    job = (
        doc.processing_jobs
        .prefetch_related("fields")
        .order_by("-created_at")
        .first()
    )
    if job is None:
        messages.error(request, "Для документа пока нет AI-обработки.")
        return redirect("dms:document_detail", pk=doc.pk)

    if request.method == "POST":
        fields = list(job.fields.all())
        for field in fields:
            old_status = field.status
            field.value = request.POST.get(f"field_{field.id}", field.value).strip()
            decision = request.POST.get(f"decision_{field.id}", "keep")
            if decision == "confirm":
                field.status = ExtractedField.Status.CONFIRMED
            elif decision == "reject":
                field.status = ExtractedField.Status.REJECTED

            if field.status != old_status:
                field.reviewed_by = request.user
                field.reviewed_at = timezone.now()
                field.save(update_fields=["value", "status", "reviewed_by", "reviewed_at", "updated_at"])
                event_type = (
                    AuditEvent.EventType.AI_FIELD_CONFIRMED
                    if field.status == ExtractedField.Status.CONFIRMED
                    else AuditEvent.EventType.AI_FIELD_REJECTED
                )
                record_audit_event(
                    event_type=event_type,
                    request=request,
                    document=doc,
                    metadata={
                        "processing_job_id": job.id,
                        "extracted_field_id": field.id,
                        "field_name": field.field_name,
                    },
                )
            else:
                field.save(update_fields=["value", "updated_at"])

        if request.POST.get("action") == "apply":
            try:
                applied_fields = apply_confirmed_fields(
                    job=job,
                    user=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, f"Не удалось применить AI-поля: {exc}")
            else:
                if applied_fields:
                    messages.success(request, "Подтвержденные AI-поля применены к документу.")
                else:
                    messages.info(request, "Нет подтвержденных AI-полей для применения.")
            return redirect("dms:document_detail", pk=doc.pk)

        messages.success(request, "Решения по AI-полям сохранены.")
        return redirect("dms:document_ai_review", pk=doc.pk)

    return render(
        request,
        "dms/document_ai_review.html",
        {
            "doc": doc,
            "job": job,
            "fields": job.fields.all(),
        },
    )


@login_required
def document_download(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user).select_related(
            "department",
            "doc_type",
        ),
        pk=pk,
    )

    if not user_can_access_document(request.user, doc):
        return HttpResponseForbidden("Нет доступа к документу")

    if not doc.file:
        raise Http404("Файл не найден")

    # ---- ЛОГ ----
    DocumentActivity.objects.create(
        user=request.user,
        document=doc,
        action=DocumentActivity.ACTION_DOWNLOADED,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_DOWNLOADED,
        request=request,
        document=doc,
        metadata={"surface": "file_download"},
    )

    return protected_file_response(doc.file, as_attachment=True)


@login_required
def document_version_view(request, pk, version_pk):
    version = get_object_or_404(
        DocumentVersion.objects.select_related("document", "document__department"),
        pk=version_pk,
        document_id=pk,
    )

    if not user_can_access_document(request.user, version.document):
        return HttpResponseForbidden("Нет доступа к документу")

    if not version.file:
        raise Http404("Файл версии не найден")

    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_VERSION_VIEWED,
        request=request,
        document_version=version,
        metadata={"surface": "version_file_view"},
    )

    return protected_file_response(version.file, as_attachment=False)


@login_required
def document_version_download(request, pk, version_pk):
    version = get_object_or_404(
        DocumentVersion.objects.select_related("document", "document__department"),
        pk=version_pk,
        document_id=pk,
    )

    if not user_can_access_document(request.user, version.document):
        return HttpResponseForbidden("Нет доступа к документу")

    if not version.file:
        raise Http404("Файл версии не найден")

    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_VERSION_DOWNLOADED,
        request=request,
        document_version=version,
        metadata={"surface": "version_file_download"},
    )

    return protected_file_response(version.file, as_attachment=True)


@login_required
@require_POST
def _legacy_document_change_status(request, pk, status):
    doc = get_object_or_404(
        get_allowed_documents(request.user),
        pk=pk,
    )

    valid_statuses = {
        Document.Status.DRAFT,
        Document.Status.APPROVED,
        Document.Status.ARCHIVED,
    }
    if status not in valid_statuses:
        return HttpResponseForbidden("Недопустимый статус")

    if not can_change_document_status(request.user, doc, status):
        return HttpResponseForbidden("Нет прав на смену статуса")

    if doc.status != status:
        previous_status = doc.status
        doc.status = status
        doc.save(update_fields=["status"])
        version = doc.create_version(uploaded_by=request.user)
        action = {
            Document.Status.APPROVED: DocumentActivity.ACTION_UPDATED,
            Document.Status.ARCHIVED: DocumentActivity.ACTION_ARCHIVED,
            Document.Status.DRAFT: DocumentActivity.ACTION_UPDATED,
        }.get(status)
        if action:
            DocumentActivity.objects.create(
                user=request.user,
                document=doc,
                action=action,
            )
        record_audit_event(
            event_type=AuditEvent.EventType.DOCUMENT_STATUS_CHANGED,
            request=request,
            document=doc,
            document_version=version,
            metadata={
                "previous_status": previous_status,
                "new_status": status,
            },
        )

    return redirect("dms:document_detail", pk=doc.pk)


@login_required
@require_POST
def _legacy_document_review_comment_create(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user),
        pk=pk,
    )

    if not can_comment_review(request.user, doc):
        return HttpResponseForbidden("Нет прав на комментарии согласования")

    form = DocumentReviewCommentForm(request.POST)
    if form.is_valid():
        DocumentReviewComment.objects.create(
            document=doc,
            user=request.user,
            message=form.cleaned_data["message"],
        )
        messages.success(request, "Комментарий сохранен")
    else:
        messages.error(request, "Не удалось сохранить комментарий")

    return redirect("dms:document_detail", pk=doc.pk)



@login_required
def user_create(request):
    if not can_manage_users(request.user):
        return HttpResponseForbidden("Доступ запрещен")

    if request.method == "POST":
        form = UserCreateForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Пользователь успешно создан")
            return redirect("dms:user_list")
    else:
        form = UserCreateForm(user=request.user)

    return render(request, "dms/user_create.html", {"form": form})


@login_required
def user_list(request):
    if not can_manage_users(request.user):
        return HttpResponseForbidden("Доступ запрещен")

    organizations = get_user_organizations(request.user)
    users = (
        User.objects
        .filter(
            Q(organization_memberships__organization__in=organizations) |
            Q(department__organization__in=organizations)
        )
        .select_related("department")
        .distinct()
        .order_by("last_name", "first_name")
    )

    return render(request, "dms/user_list.html", {
        "users": users
    })


@login_required
def user_delete(request, pk):
    if not can_manage_users(request.user):
        return HttpResponseForbidden("Доступ запрещен")

    user_obj = get_object_or_404(User, pk=pk)

    if user_obj.id == request.user.id:
        return HttpResponseForbidden("Нельзя удалить самого себя")

    if user_obj.role == "ADMIN" and request.user.role != "ADMIN":
        return HttpResponseForbidden("Только администратор может удалять администратора")

    if request.method == "POST":
        user_obj.delete()
        messages.success(request, "Пользователь удалён")
        return redirect("dms:user_list")

    return render(request, "dms/user_delete_confirm.html", {
        "user_obj": user_obj
    })



@login_required
def document_access_manage(request, pk):
    doc = get_object_or_404(
        get_allowed_documents(request.user),
        pk=pk
        )

    form = None
    granted = None


    # --- проверка прав на управление доступами
    if request.user.role != "ADMIN":
        if not request.user.department:
            return HttpResponseForbidden("Нет отдела")

        if not (
            doc.uploaded_by_id == request.user.id
            or doc.department_id == request.user.department_id
        ):
            return render(
                request,
                "dms/document_access_manage.html",
                {
                    "error": "У вас нет прав на управление доступом"
                }
        )


    # --- POST: выдача доступа
    if request.method == "POST":
        form = DocumentAccessForm(
            request.POST,
            user=request.user,
            document=doc
        )

        if form.is_valid():
            department = form.cleaned_data["department"]

            access, created = DocumentAccess.objects.get_or_create(
                document=doc,
                department=department,
                defaults={"granted_by": request.user}
            )
            if created:
                record_audit_event(
                    event_type=AuditEvent.EventType.DOCUMENT_ACCESS_GRANTED,
                    request=request,
                    document=doc,
                    metadata={
                        "access_id": access.id,
                        "granted_department_id": department.id,
                        "granted_department_name": department.name,
                    },
                )

            return redirect(request.path)

    # --- GET
    else:
        form = DocumentAccessForm(
            user=request.user,
            document=doc
        )

    granted = (
        DocumentAccess.objects
        .filter(document=doc)
        .select_related("department", "granted_by")
        .order_by("department__name")
    )

    return render(
        request,
        "dms/document_access_manage.html",
        {
            "form": form,
            "document": doc,
            "granted": granted,
        }
    )



@login_required
@require_POST
def document_access_revoke(request, pk):
    access = get_object_or_404(
        DocumentAccess.objects.select_related("document", "granted_by", "department"),
        pk=pk
    )

    if not user_can_access_document(request.user, access.document):
        return HttpResponseForbidden("Нет прав")

    if request.user.role != "ADMIN" and (
        access.document.uploaded_by_id != request.user.id
        and access.document.department_id != request.user.department_id
    ):
        return HttpResponseForbidden("РќРµС‚ РїСЂР°РІ")

    # только владелец документа или ADMIN
    if request.user.role != "ADMIN":
        if False and access.document.uploaded_by_id != request.user.id:
            return HttpResponseForbidden("Нет прав")

    document = access.document
    document_id = access.document_id
    metadata = {
        "access_id": access.id,
        "revoked_department_id": access.department_id,
        "revoked_department_name": access.department.name,
        "granted_by_id": access.granted_by_id,
    }
    access.delete()
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_ACCESS_REVOKED,
        request=request,
        document=document,
        metadata=metadata,
    )

    return redirect(
        "dms:document_access_manage",
        pk=document_id
    )

def ai_parse_document(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)

    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    form = AiParseUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"error": form.errors.get("file", ["Invalid file"])[0]}, status=400)

    uploaded_file = form.cleaned_data["file"]

    ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
    path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix="." + ext) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            path = tmp.name

        allowed_types = set(
            DocumentType.objects.filter(
                organization__in=get_user_organizations(request.user),
            ).values_list("name", flat=True)
        )

        text = extract_text_from_file(path) or ""
        if not text.strip():
            return JsonResponse(
                _build_autofill_metadata(
                    filename=uploaded_file.name,
                    allowed_types=allowed_types,
                    user=request.user,
                )
            )

        candidate_dates = extract_candidate_dates(text)

        meta = parse_document(
            text=text,
            candidate_dates=candidate_dates,
            allowed_doc_types=allowed_types,
        )

        date_value = None
        idx = meta.get("date_index")
        if isinstance(idx, int) and 0 <= idx < len(candidate_dates):
            date_value = candidate_dates[idx].strftime("%Y-%m-%d")

        return JsonResponse(
            _build_autofill_metadata(
                filename=uploaded_file.name,
                allowed_types=allowed_types,
                user=request.user,
                text=text,
                ai_meta=meta,
                date_value=date_value,
            )
        )

    finally:
        if path:
            try:
                os.remove(path)
            except Exception:
                pass



from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from dms.models import Document
from dms.services.embedding import build_embedding


from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden

from dms.models import Document
from dms.services.embedding import build_embedding
from dms.services.vector_store import search_documents
from dms.utils import get_allowed_departments


@login_required
def semantic_search(request):
    if not request.GET:
        return redirect("dms:document_list")

    return document_list(request)



# dms/views.py
from dms.models import User


@login_required
def user_change_password(request, pk):
    if request.user.role != "ADMIN":
        return HttpResponseForbidden("Доступ запрещён")

    user_obj = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UserPasswordChangeForm(request.POST, user_obj=user_obj)
        if not form.is_valid():
            return render(request, "dms/user_change_password.html", {
                "user_obj": user_obj,
                "error": " ".join(form.non_field_errors()) or " ".join(
                    message for messages_list in form.errors.values() for message in messages_list
                ),
            })

        user_obj.set_password(form.cleaned_data["password"])
        user_obj.save(update_fields=["password"])

        return redirect("dms:user_list")

    return render(request, "dms/user_change_password.html", {
        "user_obj": user_obj
    })


from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from dms.models import Document, DocumentActivity


from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from dms.models import Document, DocumentActivity

from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from dms.models import Document, DocumentActivity
@login_required
@require_POST
def document_delete(request, pk):
    user = request.user
    doc = get_object_or_404(get_allowed_documents(user), pk=pk)

    # ============================
    # ПРАВА
    # ============================
    if user.role != "ADMIN":
        if doc.department_id != user.department_id:
            return HttpResponseForbidden("Нет прав на удаление")

    # ============================
    # ЛОГ (ДО удаления)
    # ============================
    DocumentActivity.objects.create(
        user=user,
        document=doc,
        action=DocumentActivity.ACTION_DELETED,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_DELETED,
        request=request,
        document=doc,
        metadata={
            "department_id": doc.department_id,
            "folder_id": doc.folder_id,
            "status": doc.status,
        },
    )

    # ============================
    # УДАЛЕНИЕ ИЗ QDRANT
    # ============================
    delete_document_from_index(doc.id)

    # ============================
    # УДАЛЕНИЕ ИЗ БД
    # ============================
    doc.delete()

    return redirect("dms:document_list")


from django.db.models import Count

from dms.forms import FolderManageForm


def _can_manage_folders(user):
    return user.is_authenticated and (
        user.role == "ADMIN" or user.department_id is not None
    )


def _folder_path(folder):
    ancestors = folder.get_ancestors(include_self=True)
    return " / ".join(node.name for node in ancestors)


def _folder_browser_url(*, department_id, folder_id=None):
    url = f"{redirect('dms:folder_list').url}?department={department_id}"
    if folder_id:
        url += f"&folder={folder_id}"
    return url


@login_required
def folder_list(request):
    if not _can_manage_folders(request.user):
        return HttpResponseForbidden("Нет прав на управление папками")

    allowed_departments = get_allowed_departments(request.user).order_by(
        "tree_id",
        "lft",
    )
    query_form = FolderBrowserQueryForm(
        request.GET or None,
        allowed_departments=allowed_departments,
    )
    if request.GET and not query_form.is_valid():
        return HttpResponseBadRequest("Некорректные параметры папок.")

    cleaned_query = query_form.cleaned_data if query_form.is_valid() else {}
    selected_department_id = cleaned_query.get("department")

    if selected_department_id:
        selected_department = allowed_departments.filter(id=selected_department_id).first()
    else:
        selected_department = allowed_departments.first()

    current_folder = None
    root_folders = []
    child_folders = []
    documents = []
    descendant_documents = []
    breadcrumbs = []
    total_document_count = 0
    department_folder_count = 0
    department_document_count = 0

    if selected_department:
        department_folder_count = Folder.objects.filter(
            department=selected_department
        ).count()
        department_document_count = Document.objects.filter(
            department=selected_department
        ).count()
        selected_folder_id = cleaned_query.get("folder")
        if selected_folder_id:
            current_folder = (
                Folder.objects.filter(
                    department=selected_department,
                    id=selected_folder_id,
                )
                .select_related("department", "parent")
                .first()
            )

        root_folders = list(
            Folder.objects.filter(
                department=selected_department,
                parent__isnull=True,
            )
            .select_related("department", "parent")
            .annotate(
                child_count=Count("children", distinct=True),
                document_count=Count("documents", distinct=True),
            )
            .order_by("name")
        )

        if current_folder:
            child_folders = list(
                current_folder.get_children()
                .select_related("department", "parent")
                .annotate(
                    child_count=Count("children", distinct=True),
                    document_count=Count("documents", distinct=True),
                )
                .order_by("name")
            )
            documents = list(
                current_folder.documents
                .select_related("doc_type", "uploaded_by")
                .order_by("title")
            )
            descendant_documents = list(
                Document.objects.filter(
                    folder__in=current_folder.get_descendants(),
                )
                .select_related("doc_type", "uploaded_by", "folder")
                .order_by("folder__tree_id", "folder__lft", "title")
            )
            breadcrumbs = list(current_folder.get_ancestors(include_self=True))
            total_document_count = len(documents) + len(descendant_documents)
        else:
            total_document_count = department_document_count

        for folder in root_folders + child_folders:
            folder.display_path = _folder_path(folder)
            folder.can_delete = folder.child_count == 0 and folder.document_count == 0
            folder.is_empty = folder.child_count == 0 and folder.document_count == 0

        for doc in documents + descendant_documents:
            doc.status_label, doc.status_badge = get_status_badge_meta(doc.status)
            doc.version_count = doc.versions.count() if hasattr(doc, "versions") else 1
            doc.folder_path = _folder_path(doc.folder) if doc.folder else "Без папки"

    return render(
        request,
        "dms/folder_list.html",
        {
            "departments": allowed_departments,
            "selected_department": selected_department,
            "current_folder": current_folder,
            "root_folders": root_folders,
            "child_folders": child_folders,
            "documents": documents,
            "descendant_documents": descendant_documents,
            "total_document_count": total_document_count,
            "department_folder_count": department_folder_count,
            "department_document_count": department_document_count,
            "breadcrumbs": breadcrumbs,
        },
    )


@login_required
def folder_create(request):
    if not _can_manage_folders(request.user):
        return HttpResponseForbidden("Нет прав на управление папками")

    if request.method == "POST":
        form = FolderManageForm(request.POST, user=request.user)
        if form.is_valid():
            folder = form.save()
            messages.success(request, f"Папка '{folder.name}' создана")
            return redirect(
                _folder_browser_url(
                    department_id=folder.department_id,
                    folder_id=folder.parent_id,
                )
            )
    else:
        allowed_departments = get_allowed_departments(request.user)
        initial = {}
        if request.GET.get("department"):
            department_form = DepartmentSelectionForm(
                {"department": request.GET.get("department")},
                allowed_departments=allowed_departments,
            )
            if not department_form.is_valid():
                return HttpResponseBadRequest("Некорректный отдел.")
            initial["department"] = department_form.cleaned_data["department"]

        if request.GET.get("parent"):
            parent_form = ParentFolderSelectionForm(
                {"folder": request.GET.get("parent")},
                allowed_departments=allowed_departments,
            )
            if not parent_form.is_valid():
                return HttpResponseBadRequest("Некорректная родительская папка.")
            initial["parent"] = parent_form.cleaned_data["folder"]

        form = FolderManageForm(
            user=request.user,
            initial=initial,
        )

    return render(
        request,
        "dms/folder_form.html",
        {
            "form": form,
            "page_title": "Создать папку",
            "submit_label": "Создать папку",
        },
    )


@login_required
def folder_edit(request, pk):
    if not _can_manage_folders(request.user):
        return HttpResponseForbidden("Нет прав на управление папками")

    folder = get_object_or_404(
        Folder.objects.select_related("department", "parent"),
        pk=pk,
    )
    if not get_allowed_departments(request.user).filter(
        id=folder.department_id
    ).exists():
        return HttpResponseForbidden("Нет доступа к этой папке")

    if request.method == "POST":
        form = FolderManageForm(
            request.POST,
            instance=folder,
            user=request.user,
        )
        if form.is_valid():
            folder = form.save()
            messages.success(request, f"Папка '{folder.name}' обновлена")
            return redirect(
                _folder_browser_url(
                    department_id=folder.department_id,
                    folder_id=folder.id,
                )
            )
    else:
        form = FolderManageForm(instance=folder, user=request.user)

    return render(
        request,
        "dms/folder_form.html",
        {
            "form": form,
            "folder": folder,
            "page_title": "Изменить папку",
            "submit_label": "Сохранить изменения",
        },
    )


@login_required
def folder_delete(request, pk):
    if not _can_manage_folders(request.user):
        return HttpResponseForbidden("Нет прав на управление папками")

    folder = get_object_or_404(
        Folder.objects.select_related("department", "parent"),
        pk=pk,
    )
    if not get_allowed_departments(request.user).filter(
        id=folder.department_id
    ).exists():
        return HttpResponseForbidden("Нет доступа к этой папке")

    child_count = folder.get_children().count()
    document_count = folder.documents.count()
    can_delete = child_count == 0 and document_count == 0

    if request.method == "POST":
        if not can_delete:
            return HttpResponseForbidden(
                "Нельзя удалить папку, пока в ней есть подпапки или документы"
            )

        department_id = folder.department_id
        parent_id = folder.parent_id
        folder_name = folder.name
        folder.delete()
        messages.success(request, f"Папка '{folder_name}' удалена")
        return redirect(
            _folder_browser_url(
                department_id=department_id,
                folder_id=parent_id,
            )
        )

    return render(
        request,
        "dms/folder_delete_confirm.html",
        {
            "folder": folder,
            "child_count": child_count,
            "document_count": document_count,
            "can_delete": can_delete,
        },
    )
