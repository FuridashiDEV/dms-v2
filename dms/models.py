import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from mptt.models import MPTTModel, TreeForeignKey


DEFAULT_ORGANIZATION_SLUG = "default"
DEFAULT_ORGANIZATION_NAME = "Default Organization"
AUTH_USER_MODEL = settings.AUTH_USER_MODEL
SENSITIVE_METADATA_KEY_PARTS = ("token", "secret", "password", "api_key", "apikey", "private_key", "access_key")


def validate_no_plaintext_secrets(value):
    if not isinstance(value, dict):
        return
    pending = list(value.items())
    while pending:
        key, item = pending.pop()
        normalized_key = str(key).lower()
        if any(part in normalized_key for part in SENSITIVE_METADATA_KEY_PARTS):
            raise ValidationError("Sensitive integration credentials must not be stored in metadata.")
        if isinstance(item, dict):
            pending.extend(item.items())
        elif isinstance(item, list):
            pending.extend((str(index), nested) for index, nested in enumerate(item))


class Organization(models.Model):
    name = models.CharField(_("Название организации"), max_length=255)
    slug = models.SlugField(_("Slug"), max_length=80, unique=True)
    is_active = models.BooleanField(_("Активна"), default=True)
    created_at = models.DateTimeField(_("Дата создания"), auto_now_add=True)

    class Meta:
        verbose_name = _("Организация")
        verbose_name_plural = _("Организации")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


def get_default_organization_id() -> int:
    organization, _ = Organization.objects.get_or_create(
        slug=DEFAULT_ORGANIZATION_SLUG,
        defaults={
            "name": DEFAULT_ORGANIZATION_NAME,
            "is_active": True,
        },
    )
    return organization.id


class Department(MPTTModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="departments",
        verbose_name=_("Организация"),
        default=get_default_organization_id,
    )
    name = models.CharField(_("Название отдела"), max_length=255)
    parent = TreeForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Родительский отдел"),
    )

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        verbose_name = _("Отдел")
        verbose_name_plural = _("Отделы")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_department_name_per_organization",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if self.parent_id and (
            not self.organization_id
            or self.organization_id != self.parent.organization_id
        ):
            self.organization = self.parent.organization
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"organization"}
        super().save(*args, **kwargs)


class Folder(MPTTModel):
    name = models.CharField(max_length=255)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="folders",
        verbose_name=_("Организация"),
        default=get_default_organization_id,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="folders",
    )
    parent = TreeForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        unique_together = ("department", "parent", "name")
        verbose_name = _("Папка")
        verbose_name_plural = _("Папки")

    def save(self, *args, **kwargs):
        if self.department_id and (
            not self.organization_id
            or self.organization_id != self.department.organization_id
        ):
            self.organization = self.department.organization
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"organization"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class DocumentType(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="document_types",
        verbose_name=_("Организация"),
        default=get_default_organization_id,
    )
    name = models.CharField(_("Тип документа"), max_length=100)

    class Meta:
        verbose_name = _("Тип документа")
        verbose_name_plural = _("Типы документов")
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_document_type_name_per_organization",
            )
        ]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", _("Администратор")
        EMPLOYEE = "EMPLOYEE", _("Сотрудник")

    role = models.CharField(
        _("Роль"),
        max_length=20,
        choices=Role.choices,
        default=Role.EMPLOYEE,
        db_index=True,
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
        verbose_name=_("Отдел"),
    )
    position = models.CharField(
        _("Должность"),
        max_length=255,
        blank=True,
        default="",
    )

    class Meta:
        verbose_name = _("Пользователь")
        verbose_name_plural = _("Пользователи")

    def __str__(self) -> str:
        full_name = self.get_full_name()
        if full_name:
            return f"{full_name} ({self.username})"
        return self.username


class OrganizationMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", _("Владелец")
        ADMIN = "ADMIN", _("Администратор")
        MEMBER = "MEMBER", _("Участник")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name=_("Организация"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
        verbose_name=_("Пользователь"),
    )
    role = models.CharField(
        _("Роль в организации"),
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    is_active = models.BooleanField(_("Активен"), default=True)
    created_at = models.DateTimeField(_("Дата создания"), auto_now_add=True)

    class Meta:
        verbose_name = _("Участник организации")
        verbose_name_plural = _("Участники организаций")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_organization_member",
            )
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization}"


def document_upload_path(instance, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dept_id = instance.department_id or "unknown"
    folder_id = instance.folder_id or "root"
    return f"documents/{dept_id}/{folder_id}/{safe_name}"


class Document(models.Model):
    class Language(models.TextChoices):
        RU = "RU", _("Русский")
        KK = "KK", _("Казахский")
        EN = "EN", _("Английский")
        MIXED = "MIXED", _("Смешанный")
        UNKNOWN = "UNKNOWN", _("Не определен")

    class FormatRisk(models.TextChoices):
        LOW = "LOW", _("Низкий")
        MEDIUM = "MEDIUM", _("Средний")
        HIGH = "HIGH", _("Высокий")
        UNKNOWN = "UNKNOWN", _("Не определен")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Черновик")
        IN_REVIEW = "IN_REVIEW", _("In review")
        CHANGES_REQUESTED = "CHANGES_REQUESTED", _("Changes requested")
        REJECTED = "REJECTED", _("Rejected")
        APPROVED = "APPROVED", _("Актуальный")
        ARCHIVED = "ARCHIVED", _("В архиве")

    search_text_normalized = models.TextField(blank=True, default="")
    search_entities = models.JSONField(default=dict, blank=True)
    search_embedding_model = models.CharField(max_length=255, blank=True, default="")
    search_index_version = models.PositiveIntegerField(default=0)
    search_indexed_at = models.DateTimeField(null=True, blank=True)
    public_id = models.UUIDField(
        _("Публичный идентификатор"),
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )
    extracted_text = models.TextField(
        blank=True,
        verbose_name=_("Извлеченный текст"),
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("Организация"),
        default=get_default_organization_id,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("Отдел"),
    )
    folder = models.ForeignKey(
        Folder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("Папка"),
    )
    doc_type = models.ForeignKey(
        DocumentType,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("Тип документа"),
        null=True,
        blank=True,
    )
    title = models.CharField(_("Название документа"), max_length=255)
    doc_date = models.DateField(
        _("Дата документа"),
        null=True,
        blank=True,
        help_text=_("Может быть пустой на этапе загрузки"),
    )
    description = models.TextField(
        _("Краткое описание"),
        blank=True,
        default="",
    )
    language = models.CharField(
        _("Язык документа"),
        max_length=20,
        choices=Language.choices,
        default=Language.UNKNOWN,
        db_index=True,
    )
    document_author = models.CharField(
        _("Автор документа"),
        max_length=255,
        blank=True,
        default="",
    )
    retention_category = models.CharField(
        _("Категория хранения"),
        max_length=255,
        blank=True,
        default="",
    )
    retention_until = models.DateField(
        _("Срок хранения до"),
        null=True,
        blank=True,
    )
    legal_hold = models.BooleanField(
        _("Юридическое удержание"),
        default=False,
    )
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    file = models.FileField(
        _("Файл"),
        upload_to=document_upload_path,
        max_length=255,
    )
    source_file_name = models.CharField(
        _("Исходное имя файла"),
        max_length=255,
        blank=True,
        default="",
    )
    mime_type = models.CharField(
        _("MIME-тип"),
        max_length=255,
        blank=True,
        default="",
    )
    checksum_sha256 = models.CharField(
        _("Контрольная сумма SHA-256"),
        max_length=64,
        blank=True,
        default="",
        db_index=True,
    )
    source_system = models.CharField(
        _("Источник документа"),
        max_length=255,
        blank=True,
        default="",
    )
    format_risk_level = models.CharField(
        _("Риск устаревания формата"),
        max_length=20,
        choices=FormatRisk.choices,
        default=FormatRisk.UNKNOWN,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_documents",
        verbose_name=_("Загрузил"),
    )
    created_at = models.DateTimeField(
        _("Дата загрузки"),
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Документ")
        verbose_name_plural = _("Документы")
        ordering = ["-doc_date", "-id"]
        indexes = [
            models.Index(fields=["organization", "-doc_date"]),
            models.Index(fields=["department", "-doc_date"]),
            models.Index(fields=["doc_type", "-doc_date"]),
            models.Index(fields=["folder"]),
            models.Index(fields=["status"]),
            models.Index(fields=["language"]),
            models.Index(fields=["retention_until"]),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if self.department_id and (
            not self.organization_id
            or self.organization_id != self.department.organization_id
        ):
            self.organization = self.department.organization
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"organization"}
        super().save(*args, **kwargs)

    @property
    def latest_version(self):
        return self.versions.order_by("-number").first()

    @property
    def current_version_number(self) -> int:
        latest = self.latest_version
        if latest:
            return latest.number
        return 1 if self.file else 0

    def create_version(self, *, uploaded_by=None):
        latest = self.latest_version
        next_number = 1 if latest is None else latest.number + 1
        checksum_sha256 = self.checksum_sha256
        if not checksum_sha256 and self.file:
            from dms.services.preservation import calculate_file_sha256

            checksum_sha256 = calculate_file_sha256(self.file)

        return DocumentVersion.objects.create(
            document=self,
            organization=self.organization,
            number=next_number,
            title=self.title,
            description=self.description,
            status=self.status,
            doc_type=self.doc_type,
            doc_date=self.doc_date,
            department=self.department,
            folder=self.folder,
            language=self.language,
            document_author=self.document_author,
            retention_category=self.retention_category,
            retention_until=self.retention_until,
            legal_hold=self.legal_hold,
            extracted_text=self.extracted_text,
            file=self.file.name,
            source_file_name=self.source_file_name,
            mime_type=self.mime_type,
            checksum_sha256=checksum_sha256,
            source_system=self.source_system,
            format_risk_level=self.format_risk_level,
            uploaded_by=uploaded_by or self.uploaded_by,
        )


class DocumentVersion(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name=_("Документ"),
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="document_versions",
        verbose_name=_("Организация"),
    )
    number = models.PositiveIntegerField(_("Версия"))
    title = models.CharField(_("Название документа"), max_length=255)
    description = models.TextField(_("Краткое описание"), blank=True, default="")
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Document.Status.choices,
        default=Document.Status.DRAFT,
    )
    doc_type = models.ForeignKey(
        DocumentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_versions",
        verbose_name=_("Тип документа"),
    )
    doc_date = models.DateField(
        _("Дата документа"),
        null=True,
        blank=True,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="document_versions",
        verbose_name=_("Отдел"),
    )
    folder = models.ForeignKey(
        Folder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="document_versions",
        verbose_name=_("Папка"),
    )
    language = models.CharField(
        _("Язык документа"),
        max_length=20,
        choices=Document.Language.choices,
        default=Document.Language.UNKNOWN,
    )
    document_author = models.CharField(
        _("Автор документа"),
        max_length=255,
        blank=True,
        default="",
    )
    retention_category = models.CharField(
        _("Категория хранения"),
        max_length=255,
        blank=True,
        default="",
    )
    retention_until = models.DateField(
        _("Срок хранения до"),
        null=True,
        blank=True,
    )
    legal_hold = models.BooleanField(
        _("Юридическое удержание"),
        default=False,
    )
    extracted_text = models.TextField(
        blank=True,
        verbose_name=_("Извлеченный текст"),
    )
    file = models.FileField(_("Файл версии"), max_length=255)
    source_file_name = models.CharField(
        _("Исходное имя файла"),
        max_length=255,
        blank=True,
        default="",
    )
    mime_type = models.CharField(
        _("MIME-тип"),
        max_length=255,
        blank=True,
        default="",
    )
    checksum_sha256 = models.CharField(
        _("Контрольная сумма SHA-256"),
        max_length=64,
        blank=True,
        default="",
    )
    source_system = models.CharField(
        _("Источник документа"),
        max_length=255,
        blank=True,
        default="",
    )
    format_risk_level = models.CharField(
        _("Риск устаревания формата"),
        max_length=20,
        choices=Document.FormatRisk.choices,
        default=Document.FormatRisk.UNKNOWN,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_document_versions",
        verbose_name=_("Загрузил"),
    )
    created_at = models.DateTimeField(_("Дата версии"), auto_now_add=True)

    class Meta:
        verbose_name = _("Версия документа")
        verbose_name_plural = _("Версии документов")
        ordering = ["-number", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "number"],
                name="unique_document_version_number",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "-created_at"],
                name="dms_docver_org_created_idx",
            ),
            models.Index(
                fields=["document", "-number"],
                name="dms_docver_doc_number_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document.title} v{self.number}"


class SearchIndexVersion(models.Model):
    embedding_model = models.CharField(_("Embedding model"), max_length=255)
    embedding_dimension = models.PositiveIntegerField(_("Embedding dimension"))
    chunking_version = models.CharField(_("Chunking version"), max_length=40, default="chunking-v1")
    normalization_version = models.CharField(_("Normalization version"), max_length=40, default="normalization-v1")
    qdrant_collection = models.CharField(_("Qdrant collection"), max_length=255)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Search index version")
        verbose_name_plural = _("Search index versions")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "embedding_model",
                    "embedding_dimension",
                    "chunking_version",
                    "normalization_version",
                    "qdrant_collection",
                ],
                name="unique_search_index_version_config",
            )
        ]
        indexes = [
            models.Index(fields=["is_active", "qdrant_collection"]),
            models.Index(fields=["embedding_model", "embedding_dimension"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.embedding_model}/{self.embedding_dimension} "
            f"{self.chunking_version}/{self.normalization_version}"
        )


class DocumentSearchIndexState(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        INDEXED = "INDEXED", _("Indexed")
        STALE = "STALE", _("Stale")
        FAILED = "FAILED", _("Failed")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="document_search_index_states",
        verbose_name=_("Organization"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="search_index_states",
        verbose_name=_("Document"),
    )
    document_version = models.ForeignKey(
        DocumentVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="search_index_states",
        verbose_name=_("Document version"),
    )
    index_version = models.ForeignKey(
        SearchIndexVersion,
        on_delete=models.PROTECT,
        related_name="document_states",
        verbose_name=_("Search index version"),
    )
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    indexed_at = models.DateTimeField(_("Indexed at"), null=True, blank=True)
    chunks_count = models.PositiveIntegerField(_("Chunks count"), default=0)
    qdrant_collection = models.CharField(_("Qdrant collection"), max_length=255)
    content_hash = models.CharField(_("Content hash"), max_length=64, blank=True, default="")
    point_ids = models.JSONField(_("Qdrant point IDs"), default=list, blank=True)
    last_error = models.TextField(_("Last error"), blank=True, default="")
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Document search index state")
        verbose_name_plural = _("Document search index states")
        ordering = ["document_id", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "index_version"],
                name="unique_document_search_index_state",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["document", "status"]),
            models.Index(fields=["index_version", "status"]),
            models.Index(fields=["qdrant_collection", "status"]),
        ]

    def clean(self):
        super().clean()
        if self.document_id and self.organization_id and self.document.organization_id != self.organization_id:
            raise ValidationError("Search index state organization must match document organization.")
        if (
            self.document_version_id
            and self.document_id
            and self.document_version.document_id != self.document_id
        ):
            raise ValidationError("Search index state version must belong to the document.")

    def __str__(self) -> str:
        return f"{self.document_id} / {self.index_version_id} / {self.status}"


class DocumentRelation(models.Model):
    class RelationType(models.TextChoices):
        CONTRACT_TO_APPENDIX = "CONTRACT_TO_APPENDIX", _("Contract to appendix")
        CONTRACT_TO_INVOICE = "CONTRACT_TO_INVOICE", _("Contract to invoice")
        CONTRACT_TO_ACT = "CONTRACT_TO_ACT", _("Contract to act")
        CONTRACT_TO_ADDITIONAL_AGREEMENT = "CONTRACT_TO_ADDITIONAL_AGREEMENT", _("Contract to additional agreement")
        PARENT_CHILD = "PARENT_CHILD", _("Parent child")
        DUPLICATE = "DUPLICATE", _("Duplicate")
        REFERENCES = "REFERENCES", _("References")
        SAME_COUNTERPARTY = "SAME_COUNTERPARTY", _("Same counterparty")
        SAME_PROJECT = "SAME_PROJECT", _("Same project")
        REPLACED_BY = "REPLACED_BY", _("Replaced by")
        PRIMARY_DOCUMENT = "PRIMARY_DOCUMENT", _("Primary document")
        ADDENDUM = "ADDENDUM", _("Addendum")
        ACT = "ACT", _("Act")
        INVOICE = "INVOICE", _("Invoice")
        SIGNED_SCAN = "SIGNED_SCAN", _("Signed scan")
        REVISION = "REVISION", _("Revision")
        OTHER = "OTHER", _("Other")
        REPLACES = "REPLACES", _("Заменяет")
        APPENDIX_TO = "APPENDIX_TO", _("Приложение к")
        RELATED_TO = "RELATED_TO", _("Связан с")
        MENTIONS = "MENTIONS", _("Упоминает")

    class Source(models.TextChoices):
        MANUAL = "MANUAL", _("Manual")
        SYSTEM_SUGGESTION = "SYSTEM_SUGGESTION", _("System suggestion")
        AI_SUGGESTION = "AI_SUGGESTION", _("AI suggestion")
        IMPORTED = "IMPORTED", _("Imported")

    from_document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="outgoing_relations",
        verbose_name=_("Исходный документ"),
    )
    to_document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="incoming_relations",
        verbose_name=_("Связанный документ"),
    )
    relation_type = models.CharField(
        _("Тип связи"),
        max_length=40,
        choices=RelationType.choices,
    )
    source = models.CharField(
        _("Relation source"),
        max_length=30,
        choices=Source.choices,
        default=Source.MANUAL,
        db_index=True,
    )
    is_confirmed = models.BooleanField(_("Confirmed"), default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_document_relations",
        verbose_name=_("Created by"),
    )
    confidence = models.DecimalField(
        _("Уверенность"),
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Можно использовать для AI-автосвязей"),
    )
    created_at = models.DateTimeField(_("Дата создания"), auto_now_add=True)

    class Meta:
        verbose_name = _("Связь документа")
        verbose_name_plural = _("Связи документов")
        ordering = ["relation_type", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_document", "to_document", "relation_type"],
                name="unique_document_relation",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_document=models.F("to_document")),
                name="prevent_document_self_relation",
            ),
        ]
        indexes = [
            models.Index(fields=["from_document", "relation_type"]),
            models.Index(fields=["to_document", "relation_type"]),
            models.Index(fields=["source", "is_confirmed"]),
        ]

    def __str__(self) -> str:
        return f"{self.from_document} -> {self.to_document} ({self.get_relation_type_display()})"


class DocumentActivity(models.Model):
    ACTION_UPLOADED = "UPLOADED"
    ACTION_VIEWED = "VIEWED"
    ACTION_UPDATED = "UPDATED"
    ACTION_DELETED = "DELETED"
    ACTION_DOWNLOADED = "DOWNLOADED"
    ACTION_ARCHIVED = "ARCHIVED"
    ACTION_WORKFLOW_STARTED = "WORKFLOW_STARTED"
    ACTION_WORKFLOW_APPROVED = "WORKFLOW_APPROVED"
    ACTION_WORKFLOW_REJECTED = "WORKFLOW_REJECTED"
    ACTION_WORKFLOW_CHANGES_REQUESTED = "WORKFLOW_CHANGES_REQUESTED"
    ACTION_WORKFLOW_COMMENTED = "WORKFLOW_COMMENTED"

    ACTION_CHOICES = [
        (ACTION_UPLOADED, _("Документ загружен")),
        (ACTION_VIEWED, _("Документ просмотрен")),
        (ACTION_UPDATED, _("Документ обновлен")),
        (ACTION_DELETED, _("Документ удален")),
        (ACTION_DOWNLOADED, _("Документ скачан")),
        (ACTION_ARCHIVED, _("Документ переведен в архив")),
        (ACTION_WORKFLOW_STARTED, _("Workflow started")),
        (ACTION_WORKFLOW_APPROVED, _("Workflow approved")),
        (ACTION_WORKFLOW_REJECTED, _("Workflow rejected")),
        (ACTION_WORKFLOW_CHANGES_REQUESTED, _("Workflow changes requested")),
        (ACTION_WORKFLOW_COMMENTED, _("Workflow commented")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_activities",
        verbose_name=_("Пользователь"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="activities",
        verbose_name=_("Документ"),
    )
    action = models.CharField(
        _("Действие"),
        max_length=40,
        choices=ACTION_CHOICES,
    )
    created_at = models.DateTimeField(_("Дата"), auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Действие с документом")
        verbose_name_plural = _("Действия с документами")
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["document", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.action} - {self.document}"


class AuditEvent(models.Model):
    class EventType(models.TextChoices):
        DOCUMENT_RELATION_CREATED = "DOCUMENT_RELATION_CREATED", _("Document relation created")
        DOCUMENT_RELATION_DELETED = "DOCUMENT_RELATION_DELETED", _("Document relation deleted")
        DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED", _("Документ загружен")
        DOCUMENT_UPDATED = "DOCUMENT_UPDATED", _("Документ обновлен")
        DOCUMENT_VIEWED = "DOCUMENT_VIEWED", _("Документ просмотрен")
        DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED", _("Документ скачан")
        DOCUMENT_VERSION_VIEWED = "DOCUMENT_VERSION_VIEWED", _("Версия документа просмотрена")
        DOCUMENT_VERSION_DOWNLOADED = "DOCUMENT_VERSION_DOWNLOADED", _("Версия документа скачана")
        DOCUMENT_DELETED = "DOCUMENT_DELETED", _("Документ удален")
        DOCUMENT_ACCESS_GRANTED = "DOCUMENT_ACCESS_GRANTED", _("Доступ к документу выдан")
        DOCUMENT_ACCESS_REVOKED = "DOCUMENT_ACCESS_REVOKED", _("Доступ к документу отозван")
        DOCUMENT_STATUS_CHANGED = "DOCUMENT_STATUS_CHANGED", _("Статус документа изменен")
        AI_PROCESSING_STARTED = "AI_PROCESSING_STARTED", _("AI-обработка начата")
        AI_PROCESSING_COMPLETED = "AI_PROCESSING_COMPLETED", _("AI-обработка завершена")
        AI_PROCESSING_FAILED = "AI_PROCESSING_FAILED", _("AI-обработка завершилась ошибкой")
        AI_FIELD_CONFIRMED = "AI_FIELD_CONFIRMED", _("AI-поле подтверждено")
        AI_FIELD_REJECTED = "AI_FIELD_REJECTED", _("AI-поле отклонено")
        AI_FIELDS_APPLIED = "AI_FIELDS_APPLIED", _("AI-поля применены к документу")
        IMPORT_BATCH_CREATED = "IMPORT_BATCH_CREATED", _("Партия импорта создана")
        IMPORT_FILE_IMPORTED = "IMPORT_FILE_IMPORTED", _("Файл импортирован")
        IMPORT_FILE_DUPLICATE = "IMPORT_FILE_DUPLICATE", _("Дубликат при импорте")
        IMPORT_FILE_FAILED = "IMPORT_FILE_FAILED", _("Ошибка импорта файла")
        WORKFLOW_STARTED = "WORKFLOW_STARTED", _("Workflow started")
        WORKFLOW_APPROVED = "WORKFLOW_APPROVED", _("Workflow approved")
        WORKFLOW_REJECTED = "WORKFLOW_REJECTED", _("Workflow rejected")
        WORKFLOW_CHANGES_REQUESTED = "WORKFLOW_CHANGES_REQUESTED", _("Workflow changes requested")
        WORKFLOW_COMMENTED = "WORKFLOW_COMMENTED", _("Workflow commented")
        WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED", _("Workflow completed")
        EXCHANGE_SENT = "EXCHANGE_SENT", _("Document exchange sent")
        EXCHANGE_OPENED = "EXCHANGE_OPENED", _("Document exchange opened")
        EXCHANGE_DOWNLOADED = "EXCHANGE_DOWNLOADED", _("Document exchange downloaded")
        EXCHANGE_ACCEPTED = "EXCHANGE_ACCEPTED", _("Document exchange accepted")
        EXCHANGE_REJECTED = "EXCHANGE_REJECTED", _("Document exchange rejected")
        EXCHANGE_COMMENTED = "EXCHANGE_COMMENTED", _("Document exchange commented")
        EXCHANGE_RECEIVED = "EXCHANGE_RECEIVED", _("B2B document exchange received")
        EXCHANGE_EXPIRED = "EXCHANGE_EXPIRED", _("Document exchange link expired")
        EXCHANGE_REVOKED = "EXCHANGE_REVOKED", _("Document exchange link revoked")
        INTEGRATION_CONNECTION_CREATED = "INTEGRATION_CONNECTION_CREATED", _("Integration connection created")
        INTEGRATION_SYNC_JOB_CREATED = "INTEGRATION_SYNC_JOB_CREATED", _("Integration sync job created")
        EXTERNAL_REFERENCE_LINKED = "EXTERNAL_REFERENCE_LINKED", _("External reference linked")
        BILLING_SUBSCRIPTION_CREATED = "BILLING_SUBSCRIPTION_CREATED", _("Billing subscription created")
        DOCUMENT_SEARCHED = "DOCUMENT_SEARCHED", _("Document search performed")

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        verbose_name=_("Организация"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        verbose_name=_("Пользователь"),
    )
    document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        verbose_name=_("Документ"),
    )
    document_version = models.ForeignKey(
        DocumentVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        verbose_name=_("Версия документа"),
    )
    event_type = models.CharField(
        _("Тип события"),
        max_length=64,
        choices=EventType.choices,
        db_index=True,
    )
    ip_address = models.GenericIPAddressField(
        _("IP-адрес"),
        null=True,
        blank=True,
    )
    user_agent = models.TextField(
        _("User-Agent"),
        blank=True,
        default="",
    )
    metadata = models.JSONField(
        _("Метаданные"),
        default=dict,
        blank=True,
    )
    created_at = models.DateTimeField(_("Дата события"), auto_now_add=True)

    class Meta:
        verbose_name = _("Audit event")
        verbose_name_plural = _("Audit events")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class SensitiveEntity(models.Model):
    class EntityType(models.TextChoices):
        IIN = "IIN", _("IIN")
        BIN = "BIN", _("BIN")
        PHONE = "PHONE", _("Phone")
        EMAIL = "EMAIL", _("Email")
        AMOUNT = "AMOUNT", _("Amount")
        PERSONAL_NAME = "PERSONAL_NAME", _("Personal name")
        OTHER_PERSONAL_DATA = "OTHER_PERSONAL_DATA", _("Other personal data")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="sensitive_entities",
        verbose_name=_("Organization"),
    )
    document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="sensitive_entities",
        verbose_name=_("Document"),
    )
    entity_type = models.CharField(_("Entity type"), max_length=40, choices=EntityType.choices, db_index=True)
    raw_value_hash = models.CharField(_("Raw value hash"), max_length=64, db_index=True)
    masked_value = models.CharField(_("Masked value"), max_length=160, blank=True, default="")
    confidence = models.DecimalField(_("Confidence"), max_digits=4, decimal_places=2, null=True, blank=True)
    source = models.CharField(_("Source"), max_length=80, blank=True, default="")
    context = models.JSONField(_("Safe context"), default=dict, blank=True, validators=[validate_no_plaintext_secrets])
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Sensitive entity")
        verbose_name_plural = _("Sensitive entities")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document", "entity_type", "raw_value_hash", "source"],
                name="unique_sensitive_entity_per_document_source",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "entity_type", "-created_at"]),
            models.Index(fields=["document", "entity_type"]),
        ]

    def clean(self):
        super().clean()
        validate_no_plaintext_secrets(self.context)

    def __str__(self) -> str:
        return f"{self.entity_type}: {self.masked_value}"


class RetentionPolicy(models.Model):
    class Scope(models.TextChoices):
        DOCUMENT = "DOCUMENT", _("Documents")
        VERSION = "VERSION", _("Document versions")
        AUDIT = "AUDIT", _("Audit events")
        PROCESSING_RESULT = "PROCESSING_RESULT", _("Processing results")
        TEMPORARY_FILE = "TEMPORARY_FILE", _("Temporary files")

    class Action(models.TextChoices):
        REVIEW_ONLY = "REVIEW_ONLY", _("Review only")
        MANUAL_DELETE_AFTER_APPROVAL = "MANUAL_DELETE_AFTER_APPROVAL", _("Manual delete after approval")
        LEGAL_HOLD = "LEGAL_HOLD", _("Legal hold")

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="retention_policies",
        verbose_name=_("Organization"),
        help_text=_("Empty organization means global default policy."),
    )
    scope = models.CharField(_("Scope"), max_length=40, choices=Scope.choices, db_index=True)
    name = models.CharField(_("Name"), max_length=160)
    retention_days = models.PositiveIntegerField(_("Retention days"), null=True, blank=True)
    action = models.CharField(_("Action"), max_length=40, choices=Action.choices, default=Action.REVIEW_ONLY)
    is_active = models.BooleanField(_("Active"), default=True)
    notes = models.TextField(_("Notes"), blank=True, default="")
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Retention policy")
        verbose_name_plural = _("Retention policies")
        ordering = ["organization__name", "scope", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "scope", "name"],
                name="unique_retention_policy_name_per_scope",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "scope", "is_active"]),
        ]

    def __str__(self) -> str:
        owner = self.organization.name if self.organization_id else "global"
        return f"{self.name} / {self.scope} / {owner}"


class UsageEvent(models.Model):
    class EventType(models.TextChoices):
        DOCUMENT_RELATION_CREATED = "document.relation_created", _("Document relation created")
        DOCUMENT_RELATION_DELETED = "document.relation_deleted", _("Document relation deleted")
        DOCUMENT_UPLOADED = "document.uploaded", _("Document uploaded")
        IMPORT_BATCH_CREATED = "import.batch_created", _("Import batch created")
        IMPORT_FILE_IMPORTED = "import.file_imported", _("Import file imported")
        IMPORT_FILE_DUPLICATE = "import.file_duplicate", _("Import file duplicate")
        IMPORT_FILE_FAILED = "import.file_failed", _("Import file failed")
        AI_PROCESSING_STARTED = "ai.processing_started", _("AI processing started")
        AI_PROCESSING_COMPLETED = "ai.processing_completed", _("AI processing completed")
        AI_PROCESSING_FAILED = "ai.processing_failed", _("AI processing failed")
        WORKFLOW_STARTED = "workflow.started", _("Workflow started")
        WORKFLOW_ACTION = "workflow.action", _("Workflow action")
        EXCHANGE_EVENT = "exchange.event", _("Exchange event")
        EVIDENCE_EXPORTED = "evidence.exported", _("Evidence exported")
        INTEGRATION_CONNECTION_CREATED = "integration.connection_created", _("Integration connection created")
        INTEGRATION_SYNC_JOB_CREATED = "integration.sync_job_created", _("Integration sync job created")
        EXTERNAL_REFERENCE_LINKED = "integration.external_reference_linked", _("External reference linked")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="usage_events",
        verbose_name=_("Organization"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="usage_events",
        verbose_name=_("User"),
    )
    document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="usage_events",
        verbose_name=_("Document"),
    )
    event_type = models.CharField(_("Event type"), max_length=80, choices=EventType.choices, db_index=True)
    source = models.CharField(_("Source"), max_length=80, blank=True, default="")
    quantity = models.PositiveIntegerField(_("Quantity"), default=1)
    metadata = models.JSONField(_("Metadata"), default=dict, blank=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Usage event")
        verbose_name_plural = _("Usage events")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["organization", "event_type", "-created_at"]),
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} / {self.organization}"


class ObservabilityMetric(models.Model):
    class Category(models.TextChoices):
        PROCESSING = "processing", _("Processing")
        QUEUE = "queue", _("Queue")
        SEARCH = "search", _("Search")
        GPU = "gpu", _("GPU")
        QDRANT = "qdrant", _("Qdrant")
        REINDEX = "reindex", _("Reindex")

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="observability_metrics",
        verbose_name=_("Organization"),
    )
    category = models.CharField(_("Category"), max_length=40, choices=Category.choices, db_index=True)
    name = models.CharField(_("Metric name"), max_length=120, db_index=True)
    value = models.FloatField(_("Value"), default=0)
    unit = models.CharField(_("Unit"), max_length=40, blank=True, default="")
    labels = models.JSONField(_("Labels"), default=dict, blank=True, validators=[validate_no_plaintext_secrets])
    recorded_at = models.DateTimeField(_("Recorded at"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Observability metric")
        verbose_name_plural = _("Observability metrics")
        ordering = ["-recorded_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "category", "-recorded_at"]),
            models.Index(fields=["name", "-recorded_at"]),
        ]

    def clean(self):
        super().clean()
        validate_no_plaintext_secrets(self.labels)

    def __str__(self) -> str:
        return f"{self.category}.{self.name}={self.value}"


class ObservabilityAlert(models.Model):
    class Severity(models.TextChoices):
        INFO = "INFO", _("Info")
        WARNING = "WARNING", _("Warning")
        CRITICAL = "CRITICAL", _("Critical")

    class Status(models.TextChoices):
        OPEN = "OPEN", _("Open")
        ACKNOWLEDGED = "ACKNOWLEDGED", _("Acknowledged")
        RESOLVED = "RESOLVED", _("Resolved")

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="observability_alerts",
        verbose_name=_("Organization"),
    )
    alert_type = models.CharField(_("Alert type"), max_length=120, db_index=True)
    severity = models.CharField(_("Severity"), max_length=20, choices=Severity.choices, default=Severity.WARNING)
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    title = models.CharField(_("Title"), max_length=255)
    details = models.JSONField(_("Details"), default=dict, blank=True, validators=[validate_no_plaintext_secrets])
    triggered_at = models.DateTimeField(_("Triggered at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)
    resolved_at = models.DateTimeField(_("Resolved at"), null=True, blank=True)

    class Meta:
        verbose_name = _("Observability alert")
        verbose_name_plural = _("Observability alerts")
        ordering = ["-triggered_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "status", "-triggered_at"]),
            models.Index(fields=["alert_type", "status"]),
        ]

    def clean(self):
        super().clean()
        validate_no_plaintext_secrets(self.details)

    def __str__(self) -> str:
        return f"{self.alert_type} / {self.status}"


class Plan(models.Model):
    class BillingInterval(models.TextChoices):
        MANUAL = "manual", _("Manual")
        MONTHLY = "monthly", _("Monthly")
        YEARLY = "yearly", _("Yearly")

    code = models.SlugField(_("Code"), max_length=80, unique=True)
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True, default="")
    billing_interval = models.CharField(
        _("Billing interval"),
        max_length=20,
        choices=BillingInterval.choices,
        default=BillingInterval.MANUAL,
    )
    price_amount = models.DecimalField(_("Price amount"), max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(_("Currency"), max_length=3, default="KZT")
    is_active = models.BooleanField(_("Active"), default=True, db_index=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Plan")
        verbose_name_plural = _("Plans")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PlanQuota(models.Model):
    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE,
        related_name="quotas",
        verbose_name=_("Plan"),
    )
    usage_event_type = models.CharField(
        _("Usage event type"),
        max_length=80,
        choices=UsageEvent.EventType.choices,
        db_index=True,
    )
    limit = models.PositiveIntegerField(_("Limit"), default=0)
    is_unlimited = models.BooleanField(_("Unlimited"), default=False)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Plan quota")
        verbose_name_plural = _("Plan quotas")
        ordering = ["plan__name", "usage_event_type"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "usage_event_type"], name="unique_plan_quota_per_event_type"),
        ]
        indexes = [
            models.Index(fields=["plan", "usage_event_type"]),
        ]

    def effective_limit(self) -> int | None:
        if self.is_unlimited:
            return None
        return self.limit

    def __str__(self) -> str:
        if self.is_unlimited:
            return f"{self.plan} / {self.usage_event_type} / unlimited"
        return f"{self.plan} / {self.usage_event_type} / {self.limit}"


class Subscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        TRIALING = "TRIALING", _("Trialing")
        PAUSED = "PAUSED", _("Paused")
        CANCELED = "CANCELED", _("Canceled")
        EXPIRED = "EXPIRED", _("Expired")

    organization = models.OneToOneField(
        Organization,
        on_delete=models.PROTECT,
        related_name="subscription",
        verbose_name=_("Organization"),
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name=_("Plan"),
    )
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    current_period_start = models.DateField(_("Current period start"), null=True, blank=True)
    current_period_end = models.DateField(_("Current period end"), null=True, blank=True)
    is_default = models.BooleanField(_("Default subscription"), default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subscriptions",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Subscription")
        verbose_name_plural = _("Subscriptions")
        ordering = ["organization__name"]
        indexes = [
            models.Index(fields=["plan", "status"]),
            models.Index(fields=["status", "current_period_end"]),
        ]

    def __str__(self) -> str:
        return f"{self.organization} / {self.plan}"


class WebhookEndpoint(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="webhook_endpoints",
        verbose_name=_("Organization"),
    )
    name = models.CharField(_("Name"), max_length=255)
    url = models.URLField(_("URL"), max_length=1000)
    event_types = models.JSONField(_("Event types"), default=list, blank=True)
    secret_hash = models.CharField(_("Secret hash"), max_length=128, blank=True, default="")
    is_active = models.BooleanField(_("Active"), default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_webhook_endpoints",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Webhook endpoint")
        verbose_name_plural = _("Webhook endpoints")
        ordering = ["organization__name", "name"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} / {self.organization}"

    def accepts_event(self, event_type: str) -> bool:
        return not self.event_types or event_type in self.event_types


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")
        CANCELED = "CANCELED", _("Canceled")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="webhook_deliveries",
        verbose_name=_("Organization"),
    )
    endpoint = models.ForeignKey(
        WebhookEndpoint,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name=_("Webhook endpoint"),
    )
    usage_event = models.ForeignKey(
        UsageEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="webhook_deliveries",
        verbose_name=_("Usage event"),
    )
    event_type = models.CharField(_("Event type"), max_length=80, db_index=True)
    payload = models.JSONField(_("Payload"), default=dict, blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveIntegerField(_("Attempt count"), default=0)
    next_attempt_at = models.DateTimeField(_("Next attempt at"), null=True, blank=True)
    response_status = models.PositiveIntegerField(_("Response status"), null=True, blank=True)
    last_error = models.TextField(_("Last error"), blank=True, default="")
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Webhook delivery")
        verbose_name_plural = _("Webhook deliveries")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["endpoint", "status", "-created_at"]),
            models.Index(fields=["usage_event", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} -> {self.endpoint}"


class IntegrationProvider(models.Model):
    class ProviderType(models.TextChoices):
        EMAIL = "email", _("Email")
        ONE_C = "1c", _("1C")
        GOOGLE_DRIVE = "google_drive", _("Google Drive")
        ONEDRIVE = "onedrive", _("OneDrive")
        SHAREPOINT = "sharepoint", _("SharePoint")
        EXTERNAL_API = "external_api", _("External API")
        OTHER = "other", _("Other")

    code = models.SlugField(_("Code"), max_length=80, unique=True)
    name = models.CharField(_("Name"), max_length=255)
    provider_type = models.CharField(_("Provider type"), max_length=40, choices=ProviderType.choices, db_index=True)
    description = models.TextField(_("Description"), blank=True, default="")
    is_active = models.BooleanField(_("Active"), default=True, db_index=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Integration provider")
        verbose_name_plural = _("Integration providers")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class IntegrationConnection(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        ACTIVE = "ACTIVE", _("Active")
        PAUSED = "PAUSED", _("Paused")
        ERROR = "ERROR", _("Error")
        DISABLED = "DISABLED", _("Disabled")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="integration_connections",
        verbose_name=_("Organization"),
    )
    provider = models.ForeignKey(
        IntegrationProvider,
        on_delete=models.PROTECT,
        related_name="connections",
        verbose_name=_("Integration provider"),
    )
    name = models.CharField(_("Name"), max_length=255)
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    credentials_metadata = models.JSONField(
        _("Credentials metadata"),
        default=dict,
        blank=True,
        validators=[validate_no_plaintext_secrets],
    )
    secret_ref = models.CharField(_("Secret reference"), max_length=255, blank=True, default="")
    settings = models.JSONField(_("Settings"), default=dict, blank=True, validators=[validate_no_plaintext_secrets])
    last_sync_at = models.DateTimeField(_("Last sync at"), null=True, blank=True)
    created_by = models.ForeignKey(
        AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_integration_connections",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Integration connection")
        verbose_name_plural = _("Integration connections")
        ordering = ["organization__name", "provider__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "name"],
                name="unique_integration_connection_name_per_provider",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["provider", "status"]),
        ]

    def clean(self):
        super().clean()
        validate_no_plaintext_secrets(self.credentials_metadata)
        validate_no_plaintext_secrets(self.settings)
        if self.secret_ref and any(part in self.secret_ref.lower() for part in ("token=", "secret=", "password=")):
            raise ValidationError({"secret_ref": "Secret reference must point to external secret storage, not contain secret values."})

    def __str__(self) -> str:
        return f"{self.name} / {self.provider}"


class IntegrationSyncJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        RUNNING = "RUNNING", _("Running")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")
        CANCELED = "CANCELED", _("Canceled")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="integration_sync_jobs",
        verbose_name=_("Organization"),
    )
    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.CASCADE,
        related_name="sync_jobs",
        verbose_name=_("Integration connection"),
    )
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="started_integration_sync_jobs",
        verbose_name=_("Started by"),
    )
    total_items = models.PositiveIntegerField(_("Total items"), default=0)
    processed_items = models.PositiveIntegerField(_("Processed items"), default=0)
    created_documents = models.PositiveIntegerField(_("Created documents"), default=0)
    linked_references = models.PositiveIntegerField(_("Linked references"), default=0)
    failed_items = models.PositiveIntegerField(_("Failed items"), default=0)
    metadata = models.JSONField(_("Metadata"), default=dict, blank=True, validators=[validate_no_plaintext_secrets])
    error_message = models.TextField(_("Error message"), blank=True, default="")
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    started_at = models.DateTimeField(_("Started at"), null=True, blank=True)
    completed_at = models.DateTimeField(_("Completed at"), null=True, blank=True)

    class Meta:
        verbose_name = _("Integration sync job")
        verbose_name_plural = _("Integration sync jobs")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["connection", "status", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def clean(self):
        super().clean()
        if self.connection_id and self.organization_id and self.connection.organization_id != self.organization_id:
            raise ValidationError("Integration sync job organization must match connection organization.")
        validate_no_plaintext_secrets(self.metadata)

    def __str__(self) -> str:
        return f"{self.connection} / {self.status}"


class ExternalReference(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="external_references",
        verbose_name=_("Organization"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="external_references",
        verbose_name=_("Document"),
    )
    provider = models.ForeignKey(
        IntegrationProvider,
        on_delete=models.PROTECT,
        related_name="external_references",
        verbose_name=_("Integration provider"),
    )
    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.CASCADE,
        related_name="external_references",
        verbose_name=_("Integration connection"),
    )
    sync_job = models.ForeignKey(
        IntegrationSyncJob,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="external_references",
        verbose_name=_("Integration sync job"),
    )
    external_id = models.CharField(_("External ID"), max_length=512)
    external_type = models.CharField(_("External type"), max_length=80, blank=True, default="")
    display_name = models.CharField(_("Display name"), max_length=255, blank=True, default="")
    external_url = models.URLField(_("External URL"), max_length=1000, blank=True, default="")
    metadata = models.JSONField(_("Metadata"), default=dict, blank=True, validators=[validate_no_plaintext_secrets])
    first_seen_at = models.DateTimeField(_("First seen at"), auto_now_add=True)
    last_seen_at = models.DateTimeField(_("Last seen at"), auto_now=True)

    class Meta:
        verbose_name = _("External reference")
        verbose_name_plural = _("External references")
        ordering = ["-last_seen_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "external_id"],
                name="unique_external_reference_per_connection",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "-last_seen_at"]),
            models.Index(fields=["document", "-last_seen_at"]),
            models.Index(fields=["provider", "external_type"]),
            models.Index(fields=["connection", "external_type"]),
        ]

    def clean(self):
        super().clean()
        if self.document_id and self.organization_id and self.document.organization_id != self.organization_id:
            raise ValidationError("External reference organization must match document organization.")
        if self.connection_id and self.organization_id and self.connection.organization_id != self.organization_id:
            raise ValidationError("External reference organization must match connection organization.")
        if self.connection_id and self.provider_id and self.connection.provider_id != self.provider_id:
            raise ValidationError("External reference provider must match connection provider.")
        if self.sync_job_id and self.connection_id and self.sync_job.connection_id != self.connection_id:
            raise ValidationError("External reference sync job must match connection.")
        validate_no_plaintext_secrets(self.metadata)

    def __str__(self) -> str:
        return f"{self.external_id} -> {self.document}"


class ProcessingProfile(models.Model):
    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="processing_profiles",
        verbose_name=_("Organization"),
        help_text=_("Empty organization means a global reusable profile."),
    )
    name = models.CharField(_("Name"), max_length=120)
    code = models.SlugField(_("Code"), max_length=80)
    description = models.TextField(_("Description"), blank=True, default="")
    is_active = models.BooleanField(_("Active"), default=True)
    max_concurrent_jobs = models.PositiveIntegerField(_("Max concurrent jobs"), default=2)
    max_attempts = models.PositiveIntegerField(_("Max attempts"), default=3)
    retry_backoff_seconds = models.PositiveIntegerField(_("Retry backoff seconds"), default=300)
    allowed_stages = models.JSONField(_("Allowed stages"), default=list, blank=True)
    config = models.JSONField(_("Config"), default=dict, blank=True, validators=[validate_no_plaintext_secrets])
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Processing profile")
        verbose_name_plural = _("Processing profiles")
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="unique_processing_profile_code_per_org",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(organization__isnull=True),
                name="unique_global_processing_profile_code",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["code", "is_active"]),
        ]

    def clean(self):
        super().clean()
        validate_no_plaintext_secrets(self.config)

    def __str__(self) -> str:
        if self.organization_id:
            return f"{self.name} / {self.organization}"
        return f"{self.name} / global"


class ProcessingJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает обработки")
        RUNNING = "RUNNING", _("В обработке")
        COMPLETED = "COMPLETED", _("Завершено")
        FAILED = "FAILED", _("Ошибка")
        DEAD_LETTER = "DEAD_LETTER", _("Dead letter")
        REVIEWED = "REVIEWED", _("Проверено")

    class Source(models.TextChoices):
        UPLOAD = "UPLOAD", _("Загрузка документа")
        MANUAL = "MANUAL", _("Ручной запуск")

    class Stage(models.TextChoices):
        AI_PARSE = "AI_PARSE", _("AI parse")
        OCR = "OCR", _("OCR")
        TEXT_EXTRACTION = "TEXT_EXTRACTION", _("Text extraction")
        ENTITY_EXTRACTION = "ENTITY_EXTRACTION", _("Entity extraction")
        CHUNKING = "CHUNKING", _("Chunking")
        EMBEDDING = "EMBEDDING", _("Embedding")
        RERANKING = "RERANKING", _("Reranking")
        REINDEX = "REINDEX", _("Reindex")
        FAN_OUT = "FAN_OUT", _("Fan out")
        FAN_IN = "FAN_IN", _("Fan in")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="processing_jobs",
        verbose_name=_("Организация"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="processing_jobs",
        verbose_name=_("Документ"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_processing_jobs",
        verbose_name=_("Инициатор"),
    )
    profile = models.ForeignKey(
        ProcessingProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="jobs",
        verbose_name=_("Processing profile"),
    )
    parent_job = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="child_jobs",
        verbose_name=_("Parent processing job"),
    )
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    source = models.CharField(
        _("Источник"),
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    pipeline_stage = models.CharField(
        _("Pipeline stage"),
        max_length=40,
        choices=Stage.choices,
        default=Stage.AI_PARSE,
        db_index=True,
    )
    priority = models.PositiveSmallIntegerField(_("Priority"), default=5, db_index=True)
    parser_name = models.CharField(_("Parser"), max_length=100, default="ai_parser.parse_document")
    extracted_text_length = models.PositiveIntegerField(_("Длина извлеченного текста"), default=0)
    raw_result = models.JSONField(_("Raw AI result"), default=dict, blank=True)
    attempt_count = models.PositiveIntegerField(_("Attempt count"), default=0)
    max_attempts = models.PositiveIntegerField(_("Max attempts"), default=3)
    scheduled_at = models.DateTimeField(_("Scheduled at"), default=timezone.now, db_index=True)
    next_retry_at = models.DateTimeField(_("Next retry at"), null=True, blank=True, db_index=True)
    locked_at = models.DateTimeField(_("Locked at"), null=True, blank=True)
    lock_token = models.CharField(_("Lock token"), max_length=64, blank=True, default="", db_index=True)
    idempotency_key = models.CharField(_("Idempotency key"), max_length=120, blank=True, default="", db_index=True)
    center_metadata = models.JSONField(
        _("Processing center metadata"),
        default=dict,
        blank=True,
        validators=[validate_no_plaintext_secrets],
    )
    error_message = models.TextField(_("Ошибка"), blank=True, default="")
    created_at = models.DateTimeField(_("Дата создания"), auto_now_add=True)
    started_at = models.DateTimeField(_("Дата старта"), null=True, blank=True)
    completed_at = models.DateTimeField(_("Дата завершения"), null=True, blank=True)

    class Meta:
        verbose_name = _("AI processing job")
        verbose_name_plural = _("AI processing jobs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["status", "scheduled_at", "priority"]),
            models.Index(fields=["pipeline_stage", "status"]),
            models.Index(fields=["parent_job", "status"]),
        ]

    @property
    def can_retry(self) -> bool:
        return self.attempt_count < self.max_attempts

    def clean(self):
        super().clean()
        if self.profile_id and self.organization_id and self.profile.organization_id not in (None, self.organization_id):
            raise ValidationError("Processing profile organization must match job organization or be global.")
        if self.parent_job_id and self.organization_id and self.parent_job.organization_id != self.organization_id:
            raise ValidationError("Parent processing job organization must match child job organization.")
        validate_no_plaintext_secrets(self.center_metadata)

    def __str__(self) -> str:
        return f"{self.document} / {self.status}"


class ExtractedField(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "SUGGESTED", _("Предложено")
        CONFIRMED = "CONFIRMED", _("Подтверждено")
        REJECTED = "REJECTED", _("Отклонено")
        APPLIED = "APPLIED", _("Применено")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="extracted_fields",
        verbose_name=_("Организация"),
    )
    job = models.ForeignKey(
        ProcessingJob,
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name=_("Processing job"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="extracted_fields",
        verbose_name=_("Документ"),
    )
    field_name = models.CharField(_("Поле"), max_length=64)
    label = models.CharField(_("Название поля"), max_length=128)
    value = models.TextField(_("Значение"), blank=True, default="")
    confidence = models.DecimalField(_("Уверенность"), max_digits=4, decimal_places=2, null=True, blank=True)
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.SUGGESTED,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_extracted_fields",
        verbose_name=_("Проверил"),
    )
    reviewed_at = models.DateTimeField(_("Дата проверки"), null=True, blank=True)
    applied_at = models.DateTimeField(_("Дата применения"), null=True, blank=True)
    created_at = models.DateTimeField(_("Дата создания"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Дата обновления"), auto_now=True)

    class Meta:
        verbose_name = _("Extracted field")
        verbose_name_plural = _("Extracted fields")
        ordering = ["field_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "field_name"],
                name="unique_extracted_field_per_job",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["document", "status"]),
            models.Index(fields=["job", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.document} / {self.field_name}"


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает импорта")
        PROCESSING = "PROCESSING", _("В обработке")
        COMPLETED = "COMPLETED", _("Завершено")
        COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS", _("Завершено с ошибками")
        FAILED = "FAILED", _("Ошибка")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="import_batches",
        verbose_name=_("Организация"),
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="import_batches",
        verbose_name=_("Отдел"),
    )
    folder = models.ForeignKey(
        Folder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="import_batches",
        verbose_name=_("Папка"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_batches",
        verbose_name=_("Инициатор"),
    )
    status = models.CharField(
        _("Статус"),
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    source = models.CharField(_("Источник"), max_length=50, default="multiple_upload")
    total_files = models.PositiveIntegerField(_("Всего файлов"), default=0)
    imported_files = models.PositiveIntegerField(_("Импортировано"), default=0)
    duplicate_files = models.PositiveIntegerField(_("Дубликаты"), default=0)
    failed_files = models.PositiveIntegerField(_("Ошибки"), default=0)
    created_at = models.DateTimeField(_("Дата создания"), auto_now_add=True)
    completed_at = models.DateTimeField(_("Дата завершения"), null=True, blank=True)

    class Meta:
        verbose_name = _("Import batch")
        verbose_name_plural = _("Import batches")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["created_by", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Import batch #{self.id}"


class ImportFile(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает")
        IMPORTED = "IMPORTED", _("Импортирован")
        DUPLICATE = "DUPLICATE", _("Дубликат")
        FAILED = "FAILED", _("Ошибка")

    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name="files",
        verbose_name=_("Партия импорта"),
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="import_files",
        verbose_name=_("Организация"),
    )
    document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_files",
        verbose_name=_("Созданный документ"),
    )
    duplicate_of = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicate_import_files",
        verbose_name=_("Дубликат документа"),
    )
    original_file_name = models.CharField(_("Исходное имя файла"), max_length=255)
    checksum_sha256 = models.CharField(_("SHA-256"), max_length=64, blank=True, default="", db_index=True)
    status = models.CharField(
        _("Статус"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error_message = models.TextField(_("Ошибка"), blank=True, default="")
    created_at = models.DateTimeField(_("Дата создания"), auto_now_add=True)

    class Meta:
        verbose_name = _("Import file")
        verbose_name_plural = _("Import files")
        ordering = ["id"]
        indexes = [
            models.Index(fields=["batch", "status"]),
            models.Index(fields=["organization", "checksum_sha256"]),
        ]

    def __str__(self) -> str:
        return self.original_file_name


class WorkflowTemplate(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="workflow_templates",
        verbose_name=_("Organization"),
    )
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True, default="")
    is_active = models.BooleanField(_("Active"), default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_workflow_templates",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Workflow template")
        verbose_name_plural = _("Workflow templates")
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_workflow_template_name_per_organization",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class WorkflowStepTemplate(models.Model):
    template = models.ForeignKey(
        WorkflowTemplate,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name=_("Workflow template"),
    )
    order = models.PositiveIntegerField(_("Order"))
    name = models.CharField(_("Name"), max_length=255)
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workflow_step_assignments",
        verbose_name=_("Approver user"),
    )
    approver_department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="workflow_step_templates",
        verbose_name=_("Approver department"),
    )
    instructions = models.TextField(_("Instructions"), blank=True, default="")

    class Meta:
        verbose_name = _("Workflow step template")
        verbose_name_plural = _("Workflow step templates")
        ordering = ["template", "order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "order"],
                name="unique_workflow_step_order_per_template",
            )
        ]
        indexes = [
            models.Index(fields=["template", "order"]),
            models.Index(fields=["approver_user"]),
            models.Index(fields=["approver_department"]),
        ]

    def __str__(self) -> str:
        return f"{self.template} / {self.order}. {self.name}"


class WorkflowInstance(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        CHANGES_REQUESTED = "CHANGES_REQUESTED", _("Changes requested")
        CANCELED = "CANCELED", _("Canceled")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="workflow_instances",
        verbose_name=_("Organization"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="workflow_instances",
        verbose_name=_("Document"),
    )
    template = models.ForeignKey(
        WorkflowTemplate,
        on_delete=models.PROTECT,
        related_name="instances",
        verbose_name=_("Workflow template"),
    )
    current_step_template = models.ForeignKey(
        WorkflowStepTemplate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="active_instances",
        verbose_name=_("Current step"),
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="started_workflow_instances",
        verbose_name=_("Started by"),
    )
    status = models.CharField(
        _("Status"),
        max_length=30,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    started_at = models.DateTimeField(_("Started at"), auto_now_add=True)
    completed_at = models.DateTimeField(_("Completed at"), null=True, blank=True)

    class Meta:
        verbose_name = _("Workflow instance")
        verbose_name_plural = _("Workflow instances")
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document"],
                condition=models.Q(status="ACTIVE"),
                name="unique_active_workflow_per_document",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-started_at"]),
            models.Index(fields=["document", "status"]),
            models.Index(fields=["current_step_template", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.document} / {self.status}"


class WorkflowAction(models.Model):
    class ActionType(models.TextChoices):
        START = "START", _("Start")
        APPROVE = "APPROVE", _("Approve")
        REJECT = "REJECT", _("Reject")
        REQUEST_CHANGES = "REQUEST_CHANGES", _("Request changes")
        COMMENT = "COMMENT", _("Comment")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="workflow_actions",
        verbose_name=_("Organization"),
    )
    instance = models.ForeignKey(
        WorkflowInstance,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("Workflow instance"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="workflow_actions",
        verbose_name=_("Document"),
    )
    step_template = models.ForeignKey(
        WorkflowStepTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actions",
        verbose_name=_("Workflow step"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workflow_actions",
        verbose_name=_("Actor"),
    )
    action_type = models.CharField(
        _("Action"),
        max_length=30,
        choices=ActionType.choices,
        db_index=True,
    )
    comment = models.TextField(_("Comment"), blank=True, default="")
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Workflow action")
        verbose_name_plural = _("Workflow actions")
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["instance", "created_at"]),
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action_type} / {self.document}"


class Counterparty(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="counterparties",
        verbose_name=_("Organization"),
    )
    name = models.CharField(_("Name"), max_length=255)
    email = models.EmailField(_("Email"), blank=True, default="")
    contact_name = models.CharField(_("Contact name"), max_length=255, blank=True, default="")
    is_active = models.BooleanField(_("Active"), default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_counterparties",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Counterparty")
        verbose_name_plural = _("Counterparties")
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_counterparty_name_per_organization",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self) -> str:
        return self.name


class CounterpartyContact(models.Model):
    counterparty = models.ForeignKey(
        Counterparty,
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name=_("Counterparty"),
    )
    name = models.CharField(_("Name"), max_length=255)
    email = models.EmailField(_("Email"), blank=True, default="")
    position = models.CharField(_("Position"), max_length=255, blank=True, default="")
    phone = models.CharField(_("Phone"), max_length=64, blank=True, default="")
    is_active = models.BooleanField(_("Active"), default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_counterparty_contacts",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Counterparty contact")
        verbose_name_plural = _("Counterparty contacts")
        ordering = ["counterparty__name", "name"]
        indexes = [
            models.Index(fields=["counterparty", "is_active"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self) -> str:
        if self.email:
            return f"{self.name} <{self.email}>"
        return self.name


class DocumentExchange(models.Model):
    class Direction(models.TextChoices):
        OUTGOING = "OUTGOING", _("Outgoing")
        INCOMING = "INCOMING", _("Incoming")

    class Status(models.TextChoices):
        SENT = "SENT", _("Sent")
        OPENED = "OPENED", _("Opened")
        RECEIVED = "RECEIVED", _("Received")
        ACCEPTED = "ACCEPTED", _("Accepted")
        REJECTED = "REJECTED", _("Rejected")
        EXPIRED = "EXPIRED", _("Expired")
        REVOKED = "REVOKED", _("Revoked")

    class BusinessDocumentType(models.TextChoices):
        CONTRACT = "CONTRACT", _("Contract")
        INVOICE = "INVOICE", _("Invoice")
        ACT = "ACT", _("Act")
        LETTER = "LETTER", _("Letter")
        OTHER = "OTHER", _("Other")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="document_exchanges",
        verbose_name=_("Organization"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="exchanges",
        verbose_name=_("Document"),
    )
    counterparty = models.ForeignKey(
        Counterparty,
        on_delete=models.PROTECT,
        related_name="document_exchanges",
        verbose_name=_("Counterparty"),
    )
    counterparty_contact = models.ForeignKey(
        CounterpartyContact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_exchanges",
        verbose_name=_("Counterparty contact"),
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_document_exchanges",
        verbose_name=_("Sent by"),
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="received_document_exchanges",
        verbose_name=_("Received by"),
    )
    direction = models.CharField(
        _("Direction"),
        max_length=20,
        choices=Direction.choices,
        default=Direction.OUTGOING,
        db_index=True,
    )
    business_document_type = models.CharField(
        _("Business document type"),
        max_length=40,
        choices=BusinessDocumentType.choices,
        blank=True,
        default="",
        db_index=True,
    )
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=Status.choices,
        default=Status.SENT,
        db_index=True,
    )
    token_hash = models.CharField(_("Token hash"), max_length=64, unique=True, db_index=True)
    token_hint = models.CharField(_("Token hint"), max_length=12, blank=True, default="")
    message = models.TextField(_("Message"), blank=True, default="")
    expires_at = models.DateTimeField(_("Expires at"), null=True, blank=True)
    opened_at = models.DateTimeField(_("Opened at"), null=True, blank=True)
    received_at = models.DateTimeField(_("Received at"), null=True, blank=True)
    responded_at = models.DateTimeField(_("Responded at"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Document exchange")
        verbose_name_plural = _("Document exchanges")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["counterparty", "-created_at"]),
            models.Index(fields=["counterparty_contact", "-created_at"]),
            models.Index(fields=["direction", "status", "-created_at"]),
            models.Index(fields=["business_document_type", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.document} -> {self.counterparty}"

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            self.Status.ACCEPTED,
            self.Status.REJECTED,
            self.Status.EXPIRED,
            self.Status.REVOKED,
        }

    @property
    def is_link_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def is_link_active(self) -> bool:
        return (
            self.direction == self.Direction.OUTGOING
            and self.status in {self.Status.SENT, self.Status.OPENED}
            and not self.is_link_expired
        )

    @property
    def last_downloaded_at(self):
        event = (
            self.events
            .filter(event_type=ExchangeEvent.EventType.DOWNLOADED)
            .order_by("-created_at")
            .first()
        )
        return event.created_at if event else None


class ExchangeEvent(models.Model):
    class EventType(models.TextChoices):
        SENT = "SENT", _("Sent")
        OPENED = "OPENED", _("Opened")
        DOWNLOADED = "DOWNLOADED", _("Downloaded")
        RECEIVED = "RECEIVED", _("Received")
        ACCEPTED = "ACCEPTED", _("Accepted")
        REJECTED = "REJECTED", _("Rejected")
        COMMENTED = "COMMENTED", _("Commented")
        EXPIRED = "EXPIRED", _("Expired")
        REVOKED = "REVOKED", _("Revoked")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="exchange_events",
        verbose_name=_("Organization"),
    )
    exchange = models.ForeignKey(
        DocumentExchange,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name=_("Document exchange"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="exchange_events",
        verbose_name=_("Document"),
    )
    event_type = models.CharField(
        _("Event type"),
        max_length=20,
        choices=EventType.choices,
        db_index=True,
    )
    actor_name = models.CharField(_("Actor name"), max_length=255, blank=True, default="")
    actor_email = models.EmailField(_("Actor email"), blank=True, default="")
    comment = models.TextField(_("Comment"), blank=True, default="")
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.TextField(_("User-Agent"), blank=True, default="")
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Exchange event")
        verbose_name_plural = _("Exchange events")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["exchange", "-created_at"]),
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} / {self.exchange}"


class ExchangeMessage(models.Model):
    class AuthorType(models.TextChoices):
        INTERNAL = "INTERNAL", _("Internal")
        EXTERNAL = "EXTERNAL", _("External")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="exchange_messages",
        verbose_name=_("Organization"),
    )
    exchange = models.ForeignKey(
        DocumentExchange,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name=_("Document exchange"),
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="exchange_messages",
        verbose_name=_("Document"),
    )
    counterparty = models.ForeignKey(
        Counterparty,
        on_delete=models.PROTECT,
        related_name="exchange_messages",
        verbose_name=_("Counterparty"),
    )
    counterparty_contact = models.ForeignKey(
        CounterpartyContact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="exchange_messages",
        verbose_name=_("Counterparty contact"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="exchange_messages",
        verbose_name=_("User"),
    )
    author_type = models.CharField(
        _("Author type"),
        max_length=20,
        choices=AuthorType.choices,
        db_index=True,
    )
    body = models.TextField(_("Body"))
    source_event_type = models.CharField(_("Source event type"), max_length=20, blank=True, default="")
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.TextField(_("User-Agent"), blank=True, default="")
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Exchange message")
        verbose_name_plural = _("Exchange messages")
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["exchange", "created_at"]),
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["counterparty", "-created_at"]),
            models.Index(fields=["author_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_author_type_display()} / {self.exchange}"


class Notification(models.Model):
    class Type(models.TextChoices):
        WORKFLOW_ASSIGNED = "WORKFLOW_ASSIGNED", _("Workflow assigned")
        AI_REVIEW_READY = "AI_REVIEW_READY", _("AI review ready")
        EXCHANGE_OPENED = "EXCHANGE_OPENED", _("Exchange opened")
        EXCHANGE_COMMENTED = "EXCHANGE_COMMENTED", _("Exchange commented")
        EXCHANGE_ACCEPTED = "EXCHANGE_ACCEPTED", _("Exchange accepted")
        EXCHANGE_REJECTED = "EXCHANGE_REJECTED", _("Exchange rejected")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="notifications",
        verbose_name=_("Organization"),
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("Recipient"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_notifications",
        verbose_name=_("Actor"),
    )
    notification_type = models.CharField(
        _("Notification type"),
        max_length=40,
        choices=Type.choices,
        db_index=True,
    )
    title = models.CharField(_("Title"), max_length=255)
    message = models.TextField(_("Message"), blank=True, default="")
    related_document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
        verbose_name=_("Related document"),
    )
    related_exchange = models.ForeignKey(
        DocumentExchange,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
        verbose_name=_("Related exchange"),
    )
    is_read = models.BooleanField(_("Read"), default=False, db_index=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    read_at = models.DateTimeField(_("Read at"), null=True, blank=True)

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["related_document", "-created_at"]),
            models.Index(fields=["related_exchange", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.recipient} / {self.notification_type}"

    def mark_read(self):
        if self.is_read:
            return
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at"])


class DocumentAccess(models.Model):
    document = models.ForeignKey(
        "Document",
        on_delete=models.CASCADE,
        related_name="accesses",
    )
    department = models.ForeignKey(
        "Department",
        on_delete=models.CASCADE,
        related_name="document_accesses",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "department")
