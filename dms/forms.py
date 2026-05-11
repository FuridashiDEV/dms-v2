import os
import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags

from .models import Department, Document, DocumentType, Folder, OrganizationMember
from .utils import get_allowed_departments, get_user_organizations


User = get_user_model()
MAX_FILE_MB = 50
MAX_QUERY_LENGTH = 255
DISALLOWED_FILE_EXTENSIONS = {
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".ps1",
    ".psm1",
    ".vbs",
    ".js",
    ".jar",
    ".hta",
    ".dll",
}
INVALID_NAME_PATTERN = re.compile(r"[\x00-\x1f<>:\"/\\\\|?*]+")


def department_tree_choices(queryset):
    out = []
    for department in queryset:
        prefix = "— " * getattr(department, "level", 0)
        out.append((department.id, f"{prefix}{department.name}"))
    return out


def normalize_text_input(value: str, *, collapse_whitespace: bool = True) -> str:
    sanitized = strip_tags(value or "").replace("\x00", " ").strip()
    if collapse_whitespace:
        sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized


def validate_archive_filename(filename: str) -> str:
    cleaned_name = normalize_text_input(os.path.basename(filename))
    if not cleaned_name:
        raise ValidationError("Имя файла обязательно.")
    if cleaned_name in {".", ".."}:
        raise ValidationError("Недопустимое имя файла.")
    if INVALID_NAME_PATTERN.search(cleaned_name):
        raise ValidationError("Имя файла содержит недопустимые символы.")
    return cleaned_name


def validate_folder_name(value: str) -> str:
    cleaned = normalize_text_input(value)
    if not cleaned:
        return ""
    if INVALID_NAME_PATTERN.search(cleaned):
        raise ValidationError("Название содержит недопустимые символы.")
    return cleaned


def validate_uploaded_file(uploaded_file):
    if not uploaded_file:
        return uploaded_file

    validate_archive_filename(uploaded_file.name)

    if uploaded_file.size <= 0:
        raise ValidationError("Файл пустой.")

    if uploaded_file.size > MAX_FILE_MB * 1024 * 1024:
        raise ValidationError("Файл слишком большой.")

    extension = os.path.splitext(uploaded_file.name.lower())[1]
    if extension in DISALLOWED_FILE_EXTENSIONS:
        raise ValidationError("Этот тип файла запрещен для загрузки.")

    return uploaded_file


class DocumentSearchForm(forms.Form):
    q = forms.CharField(required=False, max_length=MAX_QUERY_LENGTH)
    doc_type = forms.IntegerField(required=False, min_value=1)
    department = forms.IntegerField(required=False, min_value=1)
    folder = forms.IntegerField(required=False, min_value=1)
    status = forms.ChoiceField(
        required=False,
        choices=[("", "---------"), *Document.Status.choices],
    )
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)

    def __init__(self, *args, allowed_departments=None, **kwargs):
        self.allowed_departments = allowed_departments
        super().__init__(*args, **kwargs)

    def clean_q(self):
        return normalize_text_input(self.cleaned_data.get("q", ""))

    def clean_department(self):
        department_id = self.cleaned_data.get("department")
        if not department_id:
            return None
        if self.allowed_departments is not None and not self.allowed_departments.filter(id=department_id).exists():
            raise ValidationError("Недопустимый отдел.")
        return department_id

    def clean_folder(self):
        folder_id = self.cleaned_data.get("folder")
        if not folder_id:
            return None
        folder = Folder.objects.filter(id=folder_id).only("department_id").first()
        if not folder:
            raise ValidationError("Папка не найдена.")
        if self.allowed_departments is not None and not self.allowed_departments.filter(id=folder.department_id).exists():
            raise ValidationError("Недопустимая папка.")
        return folder_id

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        department_id = cleaned_data.get("department")
        folder_id = cleaned_data.get("folder")

        if date_from and date_to and date_from > date_to:
            raise ValidationError("Дата начала не может быть позже даты окончания.")

        if folder_id and department_id:
            folder = Folder.objects.filter(id=folder_id).only("department_id").first()
            if folder and folder.department_id != department_id:
                raise ValidationError("Папка не принадлежит выбранному отделу.")

        return cleaned_data


class SemanticSearchForm(forms.Form):
    q = forms.CharField(required=True, max_length=MAX_QUERY_LENGTH)

    def clean_q(self):
        value = normalize_text_input(self.cleaned_data["q"])
        if not value:
            raise ValidationError("Поисковый запрос обязателен.")
        return value


class AiParseUploadForm(forms.Form):
    file = forms.FileField(required=True)

    def clean_file(self):
        return validate_uploaded_file(self.cleaned_data.get("file"))


class UserPasswordChangeForm(forms.Form):
    password = forms.CharField(min_length=8, max_length=128, strip=False)
    password2 = forms.CharField(min_length=8, max_length=128, strip=False)

    def __init__(self, *args, user_obj=None, **kwargs):
        self.user_obj = user_obj
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password2 = cleaned_data.get("password2")

        if password and password2 and password != password2:
            raise ValidationError("Пароли не совпадают.")

        if password:
            validate_password(password, self.user_obj)

        return cleaned_data


class FolderBrowserQueryForm(forms.Form):
    department = forms.IntegerField(required=False, min_value=1)
    folder = forms.IntegerField(required=False, min_value=1)

    def __init__(self, *args, allowed_departments=None, **kwargs):
        self.allowed_departments = allowed_departments
        super().__init__(*args, **kwargs)

    def clean_department(self):
        department_id = self.cleaned_data.get("department")
        if not department_id:
            return None
        if self.allowed_departments is not None and not self.allowed_departments.filter(id=department_id).exists():
            raise ValidationError("Недопустимый отдел.")
        return department_id

    def clean_folder(self):
        folder_id = self.cleaned_data.get("folder")
        if not folder_id:
            return None
        folder = Folder.objects.filter(id=folder_id).only("department_id").first()
        if not folder:
            raise ValidationError("Папка не найдена.")
        return folder_id

    def clean(self):
        cleaned_data = super().clean()
        department_id = cleaned_data.get("department")
        folder_id = cleaned_data.get("folder")

        if folder_id and department_id:
            folder = Folder.objects.filter(id=folder_id).only("department_id").first()
            if folder and folder.department_id != department_id:
                raise ValidationError("Папка не принадлежит выбранному отделу.")

        return cleaned_data


class DepartmentSelectionForm(forms.Form):
    department = forms.IntegerField(required=True, min_value=1)

    def __init__(self, *args, allowed_departments=None, **kwargs):
        self.allowed_departments = allowed_departments
        super().__init__(*args, **kwargs)

    def clean_department(self):
        department_id = self.cleaned_data["department"]
        if self.allowed_departments is not None and not self.allowed_departments.filter(id=department_id).exists():
            raise ValidationError("Недопустимый отдел.")
        return department_id


class ParentFolderSelectionForm(forms.Form):
    folder = forms.IntegerField(required=True, min_value=1)

    def __init__(self, *args, allowed_departments=None, **kwargs):
        self.allowed_departments = allowed_departments
        super().__init__(*args, **kwargs)

    def clean_folder(self):
        folder_id = self.cleaned_data["folder"]
        folder = Folder.objects.filter(id=folder_id).only("department_id").first()
        if not folder:
            raise ValidationError("Папка не найдена.")
        if self.allowed_departments is not None and not self.allowed_departments.filter(id=folder.department_id).exists():
            raise ValidationError("Недопустимая папка.")
        return folder_id


class DocumentUploadForm(forms.ModelForm):
    access_departments = forms.ModelMultipleChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label="Дополнительный доступ",
    )
    new_folder = forms.CharField(
        required=False,
        max_length=255,
        label="Новая папка",
    )
    new_subfolder = forms.CharField(
        required=False,
        max_length=255,
        label="Подпапка",
    )
    subfolder = forms.ModelChoiceField(
        queryset=Folder.objects.none(),
        required=False,
        label="Подпапка",
    )

    class Meta:
        model = Document
        fields = [
            "department",
            "folder",
            "new_folder",
            "new_subfolder",
            "subfolder",
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
        ]
        widgets = {
            "doc_date": forms.DateInput(attrs={"type": "date"}),
            "retention_until": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        self.fields["doc_date"].required = False
        self.fields["status"].required = True
        self.fields["language"].required = False
        self.fields["folder"].required = False
        self.fields["folder"].label_from_instance = (
            lambda obj: f"{'— ' * obj.level}{obj.name}"
        )
        self.fields["subfolder"].label_from_instance = (
            lambda obj: f"{'— ' * obj.level}{obj.name}"
        )

        if not user:
            return

        allowed_departments = get_allowed_departments(user)

        allowed_departments = allowed_departments.order_by("tree_id", "lft")
        self.fields["department"].queryset = allowed_departments
        self.fields["doc_type"].queryset = DocumentType.objects.filter(
            organization__in=get_user_organizations(user),
        ).order_by("name")

        if user.role != "ADMIN":
            self.fields["status"].choices = [
                (Document.Status.DRAFT, "Черновик"),
                (Document.Status.APPROVED, "Актуальный"),
                (Document.Status.ARCHIVED, "В архиве"),
            ]

        if user.role != "ADMIN":
            self.fields["department"].required = False
            if user.department:
                self.fields["department"].initial = user.department

        current_department = None
        if self.data.get("department"):
            try:
                current_department = allowed_departments.get(id=self.data.get("department"))
            except Department.DoesNotExist:
                current_department = None
        elif self.instance.pk and self.instance.department_id:
            current_department = self.instance.department
        elif user.role != "ADMIN":
            current_department = user.department

        if current_department:
            self.fields["folder"].queryset = Folder.objects.filter(
                department=current_department,
                parent__isnull=True,
            ).order_by("tree_id", "lft")
        else:
            self.fields["folder"].queryset = Folder.objects.none()

        current_folder = None
        if self.data.get("folder"):
            try:
                current_folder = self.fields["folder"].queryset.get(id=self.data.get("folder"))
            except Folder.DoesNotExist:
                current_folder = None
        elif self.instance.pk and self.instance.folder_id and self.instance.folder.parent_id is None:
            current_folder = self.instance.folder
        elif self.instance.pk and self.instance.folder_id and self.instance.folder.parent_id is not None:
            current_folder = self.instance.folder.parent
            self.fields["folder"].initial = current_folder
            self.fields["subfolder"].initial = self.instance.folder

        if current_folder:
            self.fields["subfolder"].queryset = Folder.objects.filter(
                department=current_folder.department,
                parent=current_folder,
            ).order_by("tree_id", "lft")
        else:
            self.fields["subfolder"].queryset = Folder.objects.none()

        if user.role == "ADMIN":
            self.fields["access_departments"].queryset = allowed_departments
        elif user.department:
            self.fields["access_departments"].queryset = (
                user.department.get_descendants(include_self=False).order_by("tree_id", "lft")
            )
        else:
            self.fields["access_departments"].queryset = Department.objects.none()

    def clean_department(self):
        department = self.cleaned_data.get("department")

        if self.user.role == "ADMIN":
            return department

        if not department and self.user and self.user.department_id:
            department = self.user.department

        if not department:
            raise ValidationError("Отдел обязателен.")

        allowed_departments = self.user.department.get_descendants(include_self=True)
        if department not in allowed_departments:
            raise ValidationError("Недопустимый отдел.")

        return department

    def clean_title(self):
        title = normalize_text_input(self.cleaned_data.get("title", ""))
        if not title:
            raise ValidationError("Название документа обязательно.")
        return title

    def clean_description(self):
        return normalize_text_input(
            self.cleaned_data.get("description", ""),
            collapse_whitespace=False,
        )

    def clean_document_author(self):
        return normalize_text_input(self.cleaned_data.get("document_author", ""))

    def clean_retention_category(self):
        return normalize_text_input(self.cleaned_data.get("retention_category", ""))

    def clean_source_system(self):
        return normalize_text_input(self.cleaned_data.get("source_system", ""))

    def clean_new_folder(self):
        return validate_folder_name(self.cleaned_data.get("new_folder", ""))

    def clean_new_subfolder(self):
        return validate_folder_name(self.cleaned_data.get("new_subfolder", ""))

    def clean_access_departments(self):
        departments = self.cleaned_data.get("access_departments")
        if not self.user or self.user.role == "ADMIN" or not self.user.department_id:
            return departments

        allowed_ids = set(
            self.user.department.get_descendants(include_self=False).values_list("id", flat=True)
        )
        submitted_ids = set(departments.values_list("id", flat=True))
        if not submitted_ids.issubset(allowed_ids):
            raise ValidationError("Недопустимый список отделов доступа.")
        return departments

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get("department")
        folder = cleaned_data.get("folder")
        subfolder = cleaned_data.get("subfolder")
        new_folder = cleaned_data.get("new_folder") or ""
        new_subfolder = cleaned_data.get("new_subfolder") or ""

        if not department:
            raise ValidationError("Отдел обязателен.")

        if new_subfolder and not (new_folder or folder):
            raise ValidationError("Подпапка требует родительскую папку.")

        if not folder and not new_folder:
            raise ValidationError("Выберите папку или создайте новую.")

        if folder and folder.department_id != department.id:
            raise ValidationError("Нельзя использовать папку другого отдела.")

        if subfolder:
            if not folder:
                raise ValidationError("Подпапку можно выбрать только после выбора родительской папки.")
            if subfolder.parent_id != folder.id:
                raise ValidationError("Подпапка не принадлежит выбранной папке.")
            if subfolder.department_id != department.id:
                raise ValidationError("Подпапка не принадлежит выбранному отделу.")

        if new_folder and folder:
            raise ValidationError("Выберите существующую папку или создайте новую, но не оба варианта сразу.")

        doc_type = cleaned_data.get("doc_type")
        if doc_type and department and doc_type.organization_id != department.organization_id:
            raise ValidationError("Тип документа не принадлежит выбранной организации.")

        return cleaned_data

    def clean_file(self):
        return validate_uploaded_file(self.cleaned_data.get("file"))


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data]
        cleaned = []
        errors = []
        for uploaded_file in files:
            try:
                cleaned.append(super().clean(uploaded_file, initial))
            except ValidationError as exc:
                errors.extend(exc.error_list)
        if errors:
            raise ValidationError(errors)
        return cleaned


class ImportBatchForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label="Отдел",
        required=True,
    )
    folder = forms.ModelChoiceField(
        queryset=Folder.objects.none(),
        label="Папка",
        required=False,
    )
    new_folder = forms.CharField(
        label="Новая папка",
        required=False,
        max_length=255,
    )
    files = MultipleFileField(
        label="Файлы",
        widget=MultipleFileInput(attrs={"multiple": True}),
        required=True,
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        allowed_departments = get_allowed_departments(user) if user else Department.objects.none()
        allowed_departments = allowed_departments.order_by("tree_id", "lft")
        self.fields["department"].queryset = allowed_departments
        self.fields["department"].choices = department_tree_choices(allowed_departments)

        current_department = None
        if self.data.get("department"):
            try:
                current_department = allowed_departments.get(id=self.data.get("department"))
            except Department.DoesNotExist:
                current_department = None
        elif user and user.role != "ADMIN" and user.department_id:
            current_department = user.department
            self.fields["department"].initial = user.department

        if current_department:
            self.fields["folder"].queryset = Folder.objects.filter(
                department=current_department,
                parent__isnull=True,
            ).order_by("tree_id", "lft")
        else:
            self.fields["folder"].queryset = Folder.objects.none()

    def clean_department(self):
        department = self.cleaned_data.get("department")
        if self.user and self.user.role != "ADMIN" and not department and self.user.department_id:
            department = self.user.department
        if not department:
            raise ValidationError("Отдел обязателен.")
        return department

    def clean_new_folder(self):
        return validate_folder_name(self.cleaned_data.get("new_folder", ""))

    def clean_files(self):
        files = self.cleaned_data.get("files") or []
        return [validate_uploaded_file(uploaded_file) for uploaded_file in files]

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get("department")
        folder = cleaned_data.get("folder")
        new_folder = cleaned_data.get("new_folder") or ""

        if folder and department and folder.department_id != department.id:
            raise ValidationError("Папка не принадлежит выбранному отделу.")
        if folder and new_folder:
            raise ValidationError("Выберите существующую папку или создайте новую, но не оба варианта.")
        if not folder and not new_folder:
            raise ValidationError("Выберите папку или создайте новую.")

        return cleaned_data


class UserAdminChangeForm(UserChangeForm):
    new_password = forms.CharField(
        label="Новый пароль",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Если заполнить поле, пароль пользователя будет заменен.",
    )

    class Meta:
        model = User
        fields = "__all__"

    def clean_new_password(self):
        new_password = self.cleaned_data.get("new_password")
        if new_password:
            validate_password(new_password, self.instance)
        return new_password

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get("new_password")
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user


class UserCreateForm(forms.ModelForm):
    temp_password = forms.CharField(
        label="Временный пароль",
        widget=forms.PasswordInput(attrs={"placeholder": "Минимум 8 символов"}),
        min_length=8,
        required=True,
    )

    class Meta:
        model = User
        fields = [
            "last_name",
            "first_name",
            "username",
            "department",
            "position",
            "role",
        ]
        widgets = {
            "last_name": forms.TextInput(attrs={"placeholder": "Иванов"}),
            "first_name": forms.TextInput(attrs={"placeholder": "Иван"}),
            "username": forms.TextInput(attrs={"placeholder": "ivanov@university.edu"}),
            "position": forms.TextInput(attrs={"placeholder": "Например: Архивариус"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.creator_user = user
        super().__init__(*args, **kwargs)
        if user:
            departments = get_allowed_departments(user).order_by("tree_id", "lft")
        else:
            departments = Department.objects.all().order_by("tree_id", "lft")
        self.fields["department"].queryset = departments
        self.fields["department"].choices = department_tree_choices(departments)

    def clean_username(self):
        username = normalize_text_input(self.cleaned_data["username"])
        if not username:
            raise ValidationError("Логин обязателен.")
        return username

    def clean_first_name(self):
        return normalize_text_input(self.cleaned_data["first_name"])

    def clean_last_name(self):
        return normalize_text_input(self.cleaned_data["last_name"])

    def clean_position(self):
        return normalize_text_input(self.cleaned_data.get("position", ""))

    def clean_temp_password(self):
        password = self.cleaned_data["temp_password"]
        candidate = User(
            username=self.cleaned_data.get("username", ""),
            first_name=self.cleaned_data.get("first_name", ""),
            last_name=self.cleaned_data.get("last_name", ""),
        )
        validate_password(password, candidate)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["temp_password"])
        if commit:
            user.save()
            organization = None
            if user.department_id:
                organization = user.department.organization
            elif self.creator_user:
                organization = get_user_organizations(self.creator_user).order_by("name", "id").first()
            if organization:
                OrganizationMember.objects.get_or_create(
                    organization=organization,
                    user=user,
                    defaults={
                        "role": (
                            OrganizationMember.Role.ADMIN
                            if user.role == User.Role.ADMIN
                            else OrganizationMember.Role.MEMBER
                        )
                    },
                )
        return user


class DocumentAccessForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label="Отдел",
        required=True,
    )

    def __init__(self, *args, user=None, document=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user.role == "ADMIN":
            queryset = get_allowed_departments(user)
        elif user.department_id:
            queryset = user.department.get_descendants(include_self=False)
        else:
            queryset = Department.objects.none()
        if document is not None:
            queryset = queryset.filter(organization_id=document.organization_id)
        self.fields["department"].queryset = queryset.order_by("tree_id", "lft")


class FolderManageForm(forms.ModelForm):
    class Meta:
        model = Folder
        fields = ["department", "parent", "name"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Например: Отчеты 2025"})
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        allowed_departments = Department.objects.none()
        if user:
            allowed_departments = get_allowed_departments(user)

        allowed_departments = allowed_departments.order_by("tree_id", "lft")
        self.fields["department"].queryset = allowed_departments
        self.fields["department"].choices = department_tree_choices(allowed_departments)

        current_department = None
        if self.data.get("department"):
            try:
                current_department = allowed_departments.get(id=self.data.get("department"))
            except Department.DoesNotExist:
                current_department = None
        elif self.instance.pk:
            current_department = self.instance.department
        elif self.initial.get("department"):
            try:
                current_department = allowed_departments.get(id=self.initial["department"])
            except Department.DoesNotExist:
                current_department = None
        elif allowed_departments.count() == 1:
            current_department = allowed_departments.first()
            self.fields["department"].initial = current_department

        parent_queryset = Folder.objects.none()
        if current_department:
            parent_queryset = Folder.objects.filter(department=current_department).order_by("tree_id", "lft")

        if self.instance.pk:
            descendants = self.instance.get_descendants(include_self=True)
            parent_queryset = parent_queryset.exclude(id__in=descendants.values_list("id", flat=True))

        self.fields["parent"].queryset = parent_queryset
        self.fields["parent"].required = False
        self.fields["parent"].label = "Родительская папка"
        self.fields["parent"].label_from_instance = (
            lambda obj: f"{'— ' * obj.level}{obj.name}"
        )

    def clean_department(self):
        department = self.cleaned_data["department"]
        if self.user.role == "ADMIN":
            return department

        allowed_departments = self.user.department.get_descendants(include_self=True)
        if department not in allowed_departments:
            raise ValidationError("Недопустимый отдел")
        return department

    def clean_name(self):
        name = validate_folder_name(self.cleaned_data.get("name", ""))
        if not name:
            raise ValidationError("Название папки обязательно.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get("department")
        parent = cleaned_data.get("parent")

        if parent and department and parent.department_id != department.id:
            raise ValidationError("Родительская папка должна принадлежать выбранному отделу")

        return cleaned_data
