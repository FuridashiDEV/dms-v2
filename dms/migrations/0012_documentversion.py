from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_initial_versions(apps, schema_editor):
    Document = apps.get_model("dms", "Document")
    DocumentVersion = apps.get_model("dms", "DocumentVersion")

    versions = []
    for document in Document.objects.all().iterator():
        if not document.file:
            continue

        versions.append(
            DocumentVersion(
                document_id=document.id,
                number=1,
                title=document.title,
                description=document.description,
                doc_type_id=document.doc_type_id,
                doc_date=document.doc_date,
                department_id=document.department_id,
                folder_id=document.folder_id,
                extracted_text=document.extracted_text,
                file=document.file.name,
                uploaded_by_id=document.uploaded_by_id,
                created_at=document.created_at,
            )
        )

    if versions:
        DocumentVersion.objects.bulk_create(versions)


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0011_remove_document_embedding_alter_document_department_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField(verbose_name="Версия")),
                ("title", models.CharField(max_length=255, verbose_name="Название документа")),
                ("description", models.TextField(blank=True, default="", verbose_name="Краткое описание")),
                ("doc_date", models.DateField(blank=True, null=True, verbose_name="Дата документа")),
                ("extracted_text", models.TextField(blank=True, verbose_name="Извлеченный текст")),
                ("file", models.FileField(max_length=255, upload_to="", verbose_name="Файл версии")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата версии")),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="document_versions", to="dms.department", verbose_name="Отдел")),
                ("doc_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="document_versions", to="dms.documenttype", verbose_name="Тип документа")),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="dms.document", verbose_name="Документ")),
                ("folder", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="document_versions", to="dms.folder", verbose_name="Папка")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="uploaded_document_versions", to=settings.AUTH_USER_MODEL, verbose_name="Загрузил")),
            ],
            options={
                "verbose_name": "Версия документа",
                "verbose_name_plural": "Версии документов",
                "ordering": ["-number", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="documentversion",
            constraint=models.UniqueConstraint(fields=("document", "number"), name="unique_document_version_number"),
        ),
        migrations.RunPython(create_initial_versions, migrations.RunPython.noop),
    ]
