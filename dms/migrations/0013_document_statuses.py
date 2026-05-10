from django.db import migrations, models


def sync_version_statuses(apps, schema_editor):
    Document = apps.get_model("dms", "Document")
    DocumentVersion = apps.get_model("dms", "DocumentVersion")

    documents = {
        document.id: document.status
        for document in Document.objects.all().only("id", "status")
    }

    updates = []
    for version in DocumentVersion.objects.all().iterator():
        version.status = documents.get(version.document_id, "DRAFT")
        updates.append(version)

    if updates:
        DocumentVersion.objects.bulk_update(updates, ["status"])


class Migration(migrations.Migration):
    dependencies = [
        ("dms", "0012_documentversion"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Черновик"),
                    ("REVIEW", "На согласовании"),
                    ("APPROVED", "Утвержден"),
                    ("ARCHIVED", "В архиве"),
                ],
                db_index=True,
                default="DRAFT",
                max_length=20,
                verbose_name="Статус",
            ),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Черновик"),
                    ("REVIEW", "На согласовании"),
                    ("APPROVED", "Утвержден"),
                    ("ARCHIVED", "В архиве"),
                ],
                default="DRAFT",
                max_length=20,
                verbose_name="Статус",
            ),
            preserve_default=False,
        ),
        migrations.RunPython(sync_version_statuses, migrations.RunPython.noop),
    ]
