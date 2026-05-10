from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("dms", "0013_document_statuses"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentReviewComment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("message", models.TextField(verbose_name="Комментарий")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата")),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review_comments",
                        to="dms.document",
                        verbose_name="Документ",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_review_comments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Комментарий согласования",
                "verbose_name_plural": "Комментарии согласования",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="documentreviewcomment",
            index=models.Index(fields=["document", "-created_at"], name="dms_documen_documen_366f15_idx"),
        ),
        migrations.AddIndex(
            model_name="documentreviewcomment",
            index=models.Index(fields=["user", "-created_at"], name="dms_documen_user_id_896cdb_idx"),
        ),
    ]
