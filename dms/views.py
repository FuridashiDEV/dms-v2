from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import date
import logging
from difflib import SequenceMatcher
from .forms import (
    AiParseUploadForm,
    DepartmentSelectionForm,
    DocumentAccessForm,
    DocumentSearchForm,
    DocumentUploadForm,
    FolderBrowserQueryForm,
    FolderManageForm,
    ParentFolderSelectionForm,
    SemanticSearchForm,
    UserCreateForm,
    UserPasswordChangeForm,
)
from .models import AuditEvent, Department, Document, DocumentActivity, DocumentType, DocumentVersion, Folder
from dms.services.ai_parser import parse_document
from dms.services.archive_intelligence import (
    build_card_quality,
    build_relation_suggestions,
    build_retention_assistant,
    get_superseded_candidates,
)
from dms.services.document_indexing import delete_document_from_index, index_document
from dms.services.audit import record_audit_event
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
            form = self.get_form()
            form.add_error(None, "Слишком много попыток входа. Повторите позже.")
            return self.form_invalid(form)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        _reset_login_failures(self.request)
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.method == "POST" and not _is_login_rate_limited(self.request):
            _register_login_failure(self.request)
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
    doc_type_id = cleaned_filters.get("doc_type")
    department_id = cleaned_filters.get("department")
    folder_id = cleaned_filters.get("folder")
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

    if q:
        query_tokens = _tokenize_search_query(q)
        lexical_filter = (
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(extracted_text__icontains=q)
            | Q(document_author__icontains=q)
            | Q(source_file_name__icontains=q)
            | Q(public_id__icontains=q)
            | Q(doc_type__name__icontains=q)
            | Q(folder__name__icontains=q)
            | Q(department__name__icontains=q)
        )
        for token in query_tokens:
            lexical_filter |= (
                Q(title__icontains=token)
                | Q(description__icontains=token)
                | Q(extracted_text__icontains=token)
                | Q(document_author__icontains=token)
                | Q(source_file_name__icontains=token)
                | Q(doc_type__name__icontains=token)
                | Q(folder__name__icontains=token)
                | Q(department__name__icontains=token)
            )

        lexical_qs = base_qs.filter(lexical_filter).order_by("-doc_date", "-created_at")
        lexical_ids = list(lexical_qs.values_list("id", flat=True)[:120])

        embedding = build_embedding(q)
        if embedding:
            try:
                semantic_hits = search_documents(
                    embedding=embedding,
                    limit=120,
                    filters={
                        "department_id": [dept.id for dept in allowed_depts],
                    },
                )
                semantic_ids = []
                for hit in semantic_hits:
                    if not hit.get("id"):
                        continue
                    doc_id = int(hit["id"])
                    semantic_ids.append(doc_id)
                    semantic_score_map[doc_id] = float(hit.get("score") or 0.0)
            except Exception:
                semantic_ids = []
                semantic_score_map = {}

        combined_ids: list[int] = []
        for doc_id in lexical_ids + semantic_ids:
            if doc_id not in combined_ids:
                combined_ids.append(doc_id)

        if combined_ids:
            candidate_docs = list(base_qs.filter(id__in=combined_ids))
            ranked_docs: list[tuple[float, object]] = []
            for doc in candidate_docs:
                lexical_score = _document_lexical_score(doc, query_tokens)
                semantic_score = semantic_score_map.get(doc.id, 0.0)
                title_signal = _field_match_score(doc.title, query_tokens)
                description_signal = _field_match_score(doc.description, query_tokens)
                filename_signal = _field_match_score(doc.source_file_name or "", query_tokens)
                strongest_text_signal = max(title_signal, description_signal, filename_signal)

                if semantic_score < 0.2 and lexical_score < 0.18:
                    continue

                if len(query_tokens) >= 2 and strongest_text_signal < 0.34 and lexical_score < 0.18:
                    continue

                if strongest_text_signal < 0.2 and semantic_score < 0.58:
                    continue

                combined_score = (
                    semantic_score * 0.6
                    + lexical_score * 0.4
                    + (0.18 if strongest_text_signal >= 0.75 else 0.0)
                    + (0.04 if semantic_score >= 0.45 else 0.0)
                )
                ranked_docs.append((combined_score, doc))

            ranked_docs.sort(
                key=lambda item: (
                    item[0],
                    item[1].doc_date or date.min,
                    item[1].created_at,
                ),
                reverse=True,
            )
            documents = [doc for _, doc in ranked_docs[:80]]
        else:
            documents = []

        if lexical_ids and semantic_ids:
            search_mode = "hybrid"
        elif semantic_ids:
            search_mode = "semantic"
        else:
            search_mode = "text"
    else:
        documents = list(base_qs.order_by("-doc_date", "-created_at")[:120])

    for doc in documents:
        doc.can_manage_access = (
            user.role == "ADMIN"
            or doc.uploaded_by_id == user.id
            or doc.department_id == user.department_id
        )
        doc.version_count = len(doc.versions.all()) or 1
        doc.status_label, doc.status_badge = get_status_badge_meta(doc.status)
        doc.folder_path = _folder_path(doc.folder) if doc.folder else "Без папки"

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
        "status": status,
        "status_choices": status_choices,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "result_count": len(documents),
        "search_mode": search_mode,
        "selected_department": selected_department,
        "selected_folder": selected_folder,
        "selected_doc_type": selected_doc_type,
        "has_active_filters": any(
            [q, doc_type_id, department_id, folder_id, status, date_from, date_to]
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

        # =================================================
        # 1. СОЗДАНИЕ ДОКУМЕНТА (БЕЗ ПАПОК, БЕЗ AI)
        # =================================================
        doc = form.save(commit=False)
        doc.uploaded_by = user
        doc.organization = doc.department.organization
        doc.source_system = doc.source_system or "manual_upload"

        if user.role != "ADMIN":
            allowed = get_allowed_departments(user)
            if not allowed.filter(id=doc.department_id).exists():
                return HttpResponseForbidden("Нельзя загрузить в этот отдел")

        doc.save()
        form.save_m2m()
        populate_preservation_metadata(doc, form.cleaned_data.get("file"))

        # =================================================
        # 2. ПАПКИ / ПОДПАПКИ (ТОЛЬКО SERVICES)
        # =================================================
        # 1️⃣ Получаем subfolder отдельно
        subfolder = form.cleaned_data.get("subfolder")

# 2️⃣ Создаём/получаем папку (если вводилась новая)
        folder = get_or_create_folder_tree(
            department=doc.department,
            parent_folder=form.cleaned_data.get("folder"),
            folder_name=form.cleaned_data.get("new_folder"),
            subfolder_name=form.cleaned_data.get("new_subfolder"),
        )

# 3️⃣ Если выбрана подпапка — она приоритетнее
        if subfolder:
            doc.folder = subfolder
        elif folder:
            doc.folder = folder

        doc.save()

# 4️⃣ Привязка документа к папке (если у тебя отдельная логика)
        attach_document_to_folder(
            document=doc,
            folder=doc.folder,
        )           

        # =================================================
        # 3. ИЗВЛЕЧЕНИЕ ТЕКСТА
        # =================================================
        extracted_text = extract_text_from_file(doc.file.path) or ""
        doc.extracted_text = extracted_text

        # =================================================
        # 4. AI
        # =================================================
        candidate_dates = extract_candidate_dates(extracted_text)

        ai_text = " ".join(filter(None, [
            doc.title,
            doc.description,
            extracted_text,
        ])).strip()
        logger.info("Extracted text for uploaded document", extra={"text_length": len(extracted_text)})

        allowed_types = set(
            DocumentType.objects.filter(
                organization=doc.organization,
            ).values_list("name", flat=True)
        )

        meta = {}
        if ai_text:
            try:
                meta = parse_document(
                    text=ai_text,
                    candidate_dates=candidate_dates,
                    allowed_doc_types=allowed_types,
                )
            except Exception:
                meta = {}

        if isinstance(meta, dict):
            if not doc.title and meta.get("title_ru"):
                doc.title = meta["title_ru"]

            if not doc.description and meta.get("summary_ru"):
                doc.description = meta["summary_ru"]

            if not doc.doc_date:
                idx = meta.get("date_index")
                if isinstance(idx, int) and 0 <= idx < len(candidate_dates):
                    doc.doc_date = candidate_dates[idx]
                elif candidate_dates:
                    doc.doc_date = candidate_dates[0]

            if not doc.doc_type and meta.get("doc_type"):
                dt, _ = DocumentType.objects.get_or_create(
                    organization=doc.organization,
                    name=meta["doc_type"],
                )
                doc.doc_type = dt

        doc.save()
        version = doc.create_version(uploaded_by=user)

        # =================================================
        # 5. EMBEDDING + QDRANT
        # =================================================
        index_document(doc)

        # =================================================
        # 6. ДОСТУПЫ
        # =================================================
        for dept in form.cleaned_data.get("access_departments", []):
            DocumentAccess.objects.get_or_create(
                document=doc,
                department=dept,
                defaults={"granted_by": user},
            )

        # =================================================
        # 7. ЛОГ
        # =================================================
        DocumentActivity.objects.create(
            user=user,
            document=doc,
            action=DocumentActivity.ACTION_UPLOADED,
        )
        record_audit_event(
            event_type=AuditEvent.EventType.DOCUMENT_UPLOADED,
            request=request,
            document=doc,
            document_version=version,
            metadata={
                "department_id": doc.department_id,
                "folder_id": doc.folder_id,
                "status": doc.status,
            },
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

        original_doc = Document.objects.get(pk=doc.pk)
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
    )

    return FileResponse(
        doc.file.open("rb"),
        as_attachment=False,
    )


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

    doc.can_manage_access = (
        request.user.role == "ADMIN"
        or doc.uploaded_by_id == request.user.id
        or doc.department_id == request.user.department_id
    )

    versions = doc.versions.all()
    accesses = doc.accesses.all()
    activities = doc.activities.all()[:12]
    outgoing_relations = doc.outgoing_relations.select_related("to_document")
    incoming_relations = doc.incoming_relations.select_related("from_document")
    allowed_queryset = get_allowed_documents(request.user)
    relation_suggestions = build_relation_suggestions(doc, allowed_queryset)
    superseded_candidates = get_superseded_candidates(doc, allowed_queryset)
    retention_hint = build_retention_assistant(doc)
    card_quality = build_card_quality(doc)
    folder_path = _folder_path(doc.folder) if doc.folder else "Без папки"
    preview_kind = get_document_preview_kind(doc.file.name if doc.file else "")
    ai_summary = build_document_ai_summary(doc)
    similar_documents = get_similar_documents_for_user(doc, request.user)

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
            "relation_suggestions": relation_suggestions,
            "superseded_candidates": superseded_candidates,
            "retention_hint": retention_hint,
            "card_quality": card_quality,
            "folder_path": folder_path,
            "preview_kind": preview_kind,
            "ai_summary": ai_summary,
            "similar_documents": similar_documents,
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
    )

    return FileResponse(
        doc.file.open("rb"),
        as_attachment=True,
    )


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
    )

    return FileResponse(
        version.file.open("rb"),
        as_attachment=False,
    )


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
    )

    return FileResponse(
        version.file.open("rb"),
        as_attachment=True,
    )


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
