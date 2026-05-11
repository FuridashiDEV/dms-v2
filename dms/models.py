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

    ACTION_CHOICES = [
        (ACTION_UPLOADED, _("Документ загружен")),
        (ACTION_VIEWED, _("Документ просмотрен")),
        (ACTION_UPDATED, _("Документ обновлен")),
        (ACTION_DELETED, _("Документ удален")),
        (ACTION_DOWNLOADED, _("Документ скачан")),
        (ACTION_ARCHIVED, _("Документ переведен в архив")),
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
        max_length=20,
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
