import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    Document = apps.get_model("dms", "Document")
    for document in Document.objects.filter(public_id__isnull=True):
        document.public_id = uuid.uuid4()
        document.save(update_fields=["public_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0014_documentreviewcomment"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="public_id",
            field=models.UUIDField(
                null=True,
                editable=False,
                db_index=True,
                verbose_name="Публичный идентификатор",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="language",
            field=models.CharField(
                choices=[
                    ("RU", "Русский"),
                    ("KK", "Казахский"),
                    ("EN", "Английский"),
                    ("MIXED", "Смешанный"),
                    ("UNKNOWN", "Не определен"),
                ],
                db_index=True,
                default="UNKNOWN",
                max_length=20,
                verbose_name="Язык документа",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="document_author",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Автор документа"),
        ),
        migrations.AddField(
            model_name="document",
            name="retention_category",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Категория хранения"),
        ),
        migrations.AddField(
            model_name="document",
            name="retention_until",
            field=models.DateField(blank=True, null=True, verbose_name="Срок хранения до"),
        ),
        migrations.AddField(
            model_name="document",
            name="legal_hold",
            field=models.BooleanField(default=False, verbose_name="Юридическое удержание"),
        ),
        migrations.AddField(
            model_name="document",
            name="source_file_name",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Исходное имя файла"),
        ),
        migrations.AddField(
            model_name="document",
            name="mime_type",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="MIME-тип"),
        ),
        migrations.AddField(
            model_name="document",
            name="checksum_sha256",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="Контрольная сумма SHA-256"),
        ),
        migrations.AddField(
            model_name="document",
            name="source_system",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Источник документа"),
        ),
        migrations.AddField(
            model_name="document",
            name="format_risk_level",
            field=models.CharField(
                choices=[
                    ("LOW", "Низкий"),
                    ("MEDIUM", "Средний"),
                    ("HIGH", "Высокий"),
                    ("UNKNOWN", "Не определен"),
                ],
                default="UNKNOWN",
                max_length=20,
                verbose_name="Риск устаревания формата",
            ),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="language",
            field=models.CharField(
                choices=[
                    ("RU", "Русский"),
                    ("KK", "Казахский"),
                    ("EN", "Английский"),
                    ("MIXED", "Смешанный"),
                    ("UNKNOWN", "Не определен"),
                ],
                default="UNKNOWN",
                max_length=20,
                verbose_name="Язык документа",
            ),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="document_author",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Автор документа"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="retention_category",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Категория хранения"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="retention_until",
            field=models.DateField(blank=True, null=True, verbose_name="Срок хранения до"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="legal_hold",
            field=models.BooleanField(default=False, verbose_name="Юридическое удержание"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="source_file_name",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Исходное имя файла"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="mime_type",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="MIME-тип"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="checksum_sha256",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Контрольная сумма SHA-256"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="source_system",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Источник документа"),
        ),
        migrations.AddField(
            model_name="documentversion",
            name="format_risk_level",
            field=models.CharField(
                choices=[
                    ("LOW", "Низкий"),
                    ("MEDIUM", "Средний"),
                    ("HIGH", "Высокий"),
                    ("UNKNOWN", "Не определен"),
                ],
                default="UNKNOWN",
                max_length=20,
                verbose_name="Риск устаревания формата",
            ),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="document",
            name="public_id",
            field=models.UUIDField(
                default=uuid.uuid4,
                unique=True,
                editable=False,
                db_index=True,
                verbose_name="Публичный идентификатор",
            ),
        ),
    ]
