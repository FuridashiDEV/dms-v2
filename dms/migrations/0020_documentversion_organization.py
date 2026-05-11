from django.db import migrations, models
import django.db.models.deletion


def backfill_document_version_organizations(apps, schema_editor):
    Document = apps.get_model("dms", "Document")
    DocumentVersion = apps.get_model("dms", "DocumentVersion")

    documents = {
        document["id"]: document
        for document in Document.objects.values(
            "id",
            "organization_id",
            "title",
            "description",
            "status",
            "doc_type_id",
            "doc_date",
            "department_id",
            "folder_id",
            "language",
            "document_author",
            "retention_category",
            "retention_until",
            "legal_hold",
            "extracted_text",
            "file",
            "source_file_name",
            "mime_type",
            "checksum_sha256",
            "source_system",
            "format_risk_level",
            "uploaded_by_id",
            "created_at",
        )
    }

    updates = []
    for version in DocumentVersion.objects.filter(organization__isnull=True).only(
        "id",
        "document_id",
        "organization_id",
    ):
        document = documents.get(version.document_id)
        if not document:
            continue
        version.organization_id = document["organization_id"]
        updates.append(version)

    if updates:
        DocumentVersion.objects.bulk_update(updates, ["organization"])

    versioned_document_ids = set(
        DocumentVersion.objects.values_list("document_id", flat=True)
    )
    missing_versions = []
    for document_id, document in documents.items():
        if document_id in versioned_document_ids or not document["file"]:
            continue
        missing_versions.append(
            DocumentVersion(
                document_id=document_id,
                organization_id=document["organization_id"],
                number=1,
                title=document["title"],
                description=document["description"],
                status=document["status"],
                doc_type_id=document["doc_type_id"],
                doc_date=document["doc_date"],
                department_id=document["department_id"],
                folder_id=document["folder_id"],
                language=document["language"],
                document_author=document["document_author"],
                retention_category=document["retention_category"],
                retention_until=document["retention_until"],
                legal_hold=document["legal_hold"],
                extracted_text=document["extracted_text"],
                file=document["file"],
                source_file_name=document["source_file_name"],
                mime_type=document["mime_type"],
                checksum_sha256=document["checksum_sha256"],
                source_system=document["source_system"],
                format_risk_level=document["format_risk_level"],
                uploaded_by_id=document["uploaded_by_id"],
                created_at=document["created_at"],
            )
        )

    if missing_versions:
        DocumentVersion.objects.bulk_create(missing_versions)


class Migration(migrations.Migration):

    dependencies = [
        ("dms", "0019_alter_documenttype_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentversion",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="document_versions",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.RunPython(
            backfill_document_version_organizations,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="documentversion",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="document_versions",
                to="dms.organization",
                verbose_name="Организация",
            ),
        ),
        migrations.AddIndex(
            model_name="documentversion",
            index=models.Index(
                fields=["organization", "-created_at"],
                name="dms_docver_org_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="documentversion",
            index=models.Index(
                fields=["document", "-number"],
                name="dms_docver_doc_number_idx",
            ),
        ),
    ]
