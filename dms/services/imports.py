import os

from django.db import transaction
from django.utils import timezone

from dms.models import AuditEvent, Document, ImportBatch, ImportFile, UsageEvent
from dms.services.audit import record_audit_event
from dms.services.document_creation import create_document_from_uploaded_file
from dms.services.preservation import calculate_file_sha256
from dms.services.usage import record_usage_event


def _default_title(file_name: str) -> str:
    title = os.path.splitext(os.path.basename(file_name or ""))[0].strip()
    return title[:255] or "Imported document"


@transaction.atomic
def create_import_batch(
    *,
    organization,
    department,
    folder,
    created_by,
    total_files: int,
    request=None,
) -> ImportBatch:
    batch = ImportBatch.objects.create(
        organization=organization,
        department=department,
        folder=folder,
        created_by=created_by,
        total_files=total_files,
        status=ImportBatch.Status.PROCESSING,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.IMPORT_BATCH_CREATED,
        request=request,
        user=created_by,
        organization=organization,
        metadata={
            "import_batch_id": batch.id,
            "department_id": department.id,
            "folder_id": folder.id if folder else None,
            "total_files": total_files,
        },
    )
    record_usage_event(
        event_type=UsageEvent.EventType.IMPORT_BATCH_CREATED,
        organization=organization,
        user=created_by,
        source="multiple_upload",
        quantity=total_files,
        metadata={
            "import_batch_id": batch.id,
            "department_id": department.id,
            "folder_id": folder.id if folder else None,
        },
    )
    return batch


def import_uploaded_files(
    *,
    batch: ImportBatch,
    files,
    created_by,
    request=None,
) -> ImportBatch:
    imported_count = 0
    duplicate_count = 0
    failed_count = 0

    for uploaded_file in files:
        checksum_sha256 = calculate_file_sha256(uploaded_file)
        import_file = ImportFile.objects.create(
            batch=batch,
            organization=batch.organization,
            original_file_name=os.path.basename(uploaded_file.name),
            checksum_sha256=checksum_sha256,
        )

        duplicate = None
        if checksum_sha256:
            duplicate = (
                Document.objects
                .filter(
                    organization=batch.organization,
                    checksum_sha256=checksum_sha256,
                )
                .order_by("id")
                .first()
            )

        if duplicate is not None:
            import_file.status = ImportFile.Status.DUPLICATE
            import_file.duplicate_of = duplicate
            import_file.save(update_fields=["status", "duplicate_of"])
            duplicate_count += 1
            record_audit_event(
                event_type=AuditEvent.EventType.IMPORT_FILE_DUPLICATE,
                request=request,
                user=created_by,
                document=duplicate,
                metadata={
                    "import_batch_id": batch.id,
                    "import_file_id": import_file.id,
                    "original_file_name": import_file.original_file_name,
                    "checksum_sha256": checksum_sha256,
                },
            )
            record_usage_event(
                event_type=UsageEvent.EventType.IMPORT_FILE_DUPLICATE,
                user=created_by,
                document=duplicate,
                source="multiple_upload",
                metadata={
                    "import_batch_id": batch.id,
                    "import_file_id": import_file.id,
                    "original_file_name": import_file.original_file_name,
                },
            )
            continue

        try:
            document, _ = create_document_from_uploaded_file(
                uploaded_file=uploaded_file,
                department=batch.department,
                folder=batch.folder,
                title=_default_title(uploaded_file.name),
                source_system=f"import_batch:{batch.id}",
                uploaded_by=created_by,
                request=request,
                run_ai=False,
                audit_metadata={
                    "import_batch_id": batch.id,
                    "import_file_id": import_file.id,
                    "import_source": "multiple_upload",
                },
            )
        except Exception as exc:
            import_file.status = ImportFile.Status.FAILED
            import_file.error_message = str(exc)[:2000]
            import_file.save(update_fields=["status", "error_message"])
            failed_count += 1
            record_audit_event(
                event_type=AuditEvent.EventType.IMPORT_FILE_FAILED,
                request=request,
                user=created_by,
                organization=batch.organization,
                metadata={
                    "import_batch_id": batch.id,
                    "import_file_id": import_file.id,
                    "original_file_name": import_file.original_file_name,
                    "error": import_file.error_message,
                },
            )
            record_usage_event(
                event_type=UsageEvent.EventType.IMPORT_FILE_FAILED,
                organization=batch.organization,
                user=created_by,
                source="multiple_upload",
                metadata={
                    "import_batch_id": batch.id,
                    "import_file_id": import_file.id,
                    "original_file_name": import_file.original_file_name,
                },
            )
            continue

        import_file.status = ImportFile.Status.IMPORTED
        import_file.document = document
        import_file.checksum_sha256 = document.checksum_sha256 or checksum_sha256
        import_file.save(update_fields=["status", "document", "checksum_sha256"])
        imported_count += 1
        record_audit_event(
            event_type=AuditEvent.EventType.IMPORT_FILE_IMPORTED,
            request=request,
            user=created_by,
            document=document,
            metadata={
                "import_batch_id": batch.id,
                "import_file_id": import_file.id,
                "original_file_name": import_file.original_file_name,
                "checksum_sha256": import_file.checksum_sha256,
            },
        )
        record_usage_event(
            event_type=UsageEvent.EventType.IMPORT_FILE_IMPORTED,
            user=created_by,
            document=document,
            source="multiple_upload",
            metadata={
                "import_batch_id": batch.id,
                "import_file_id": import_file.id,
                "original_file_name": import_file.original_file_name,
            },
        )

    batch.imported_files = imported_count
    batch.duplicate_files = duplicate_count
    batch.failed_files = failed_count
    batch.completed_at = timezone.now()
    batch.status = (
        ImportBatch.Status.COMPLETED
        if failed_count == 0
        else ImportBatch.Status.COMPLETED_WITH_ERRORS
    )
    batch.save(
        update_fields=[
            "imported_files",
            "duplicate_files",
            "failed_files",
            "completed_at",
            "status",
        ]
    )
    return batch
