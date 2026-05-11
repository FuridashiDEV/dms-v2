import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from mptt.models import MPTTModel, TreeForeignKey


DEFAULT_ORGANIZATION_SLUG = "default"
DEFAULT_ORGANIZATION_NAME = "Default Organization"


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


class DocumentRelation(models.Model):
    class RelationType(models.TextChoices):
        REPLACES = "REPLACES", _("Заменяет")
        APPENDIX_TO = "APPENDIX_TO", _("Приложение к")
        RELATED_TO = "RELATED_TO", _("Связан с")
        MENTIONS = "MENTIONS", _("Упоминает")

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
        max_length=20,
        choices=RelationType.choices,
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


class ProcessingJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Ожидает обработки")
        RUNNING = "RUNNING", _("В обработке")
        COMPLETED = "COMPLETED", _("Завершено")
        FAILED = "FAILED", _("Ошибка")
        REVIEWED = "REVIEWED", _("Проверено")

    class Source(models.TextChoices):
        UPLOAD = "UPLOAD", _("Загрузка документа")
        MANUAL = "MANUAL", _("Ручной запуск")

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
    parser_name = models.CharField(_("Parser"), max_length=100, default="ai_parser.parse_document")
    extracted_text_length = models.PositiveIntegerField(_("Длина извлеченного текста"), default=0)
    raw_result = models.JSONField(_("Raw AI result"), default=dict, blank=True)
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
        ]

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
