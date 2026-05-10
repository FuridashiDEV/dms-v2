from django.db import migrations


def normalize_archive_statuses(apps, schema_editor):
    Document = apps.get_model("dms", "Document")
    DocumentVersion = apps.get_model("dms", "DocumentVersion")

    Document.objects.filter(status="REVIEW").update(status="DRAFT")
    DocumentVersion.objects.filter(status="REVIEW").update(status="DRAFT")


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0016_documentrelation"),
    ]

    operations = [
        migrations.RunPython(normalize_archive_statuses, migrations.RunPython.noop),
        migrations.DeleteModel(name="DocumentReviewComment"),
    ]
