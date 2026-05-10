from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0015_document_archival_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentRelation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("relation_type", models.CharField(choices=[("REPLACES", "Заменяет"), ("APPENDIX_TO", "Приложение к"), ("RELATED_TO", "Связан с"), ("MENTIONS", "Упоминает")], max_length=20, verbose_name="Тип связи")),
                ("confidence", models.DecimalField(blank=True, decimal_places=2, help_text="Можно использовать для AI-автосвязей", max_digits=4, null=True, verbose_name="Уверенность")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
                ("from_document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="outgoing_relations", to="dms.document", verbose_name="Исходный документ")),
                ("to_document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="incoming_relations", to="dms.document", verbose_name="Связанный документ")),
            ],
            options={
                "verbose_name": "Связь документа",
                "verbose_name_plural": "Связи документов",
                "ordering": ["relation_type", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="documentrelation",
            index=models.Index(fields=["from_document", "relation_type"], name="dms_documen_from_do_64c9d4_idx"),
        ),
        migrations.AddIndex(
            model_name="documentrelation",
            index=models.Index(fields=["to_document", "relation_type"], name="dms_documen_to_docu_6a8081_idx"),
        ),
        migrations.AddConstraint(
            model_name="documentrelation",
            constraint=models.UniqueConstraint(fields=("from_document", "to_document", "relation_type"), name="unique_document_relation"),
        ),
        migrations.AddConstraint(
            model_name="documentrelation",
            constraint=models.CheckConstraint(condition=~models.Q(from_document=models.F("to_document")), name="prevent_document_self_relation"),
        ),
    ]
