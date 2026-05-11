import os

from django.db import transaction

from dms.models import AuditEvent, Document, DocumentActivity, ProcessingJob
from dms.services.ai_parser import parse_document
from dms.services.ai_processing import run_document_ai_processing
from dms.services.audit import record_audit_event
from dms.services.document_indexing import index_document
from dms.services.folders import attach_document_to_folder, get_or_create_folder_tree
from dms.services.preservation import calculate_file_sha256, calculate_sha256, detect_format_risk, detect_mime_type
from dms.services.text_extractor import extract_text_from_file


def populate_document_preservation_metadata(document: Document, uploaded_file=None) -> None:
    if uploaded_file is not None:
        document.source_file_name = uploaded_file.name
        document.mime_type = detect_mime_type(uploaded_file.name)
        document.format_risk_level = detect_format_risk(uploaded_file.name)
    elif document.file:
        document.source_file_name = document.source_file_name or os.path.basename(document.file.name)
        document.mime_type = document.mime_type or detect_mime_type(document.source_file_name or document.file.name)
        document.format_risk_level = (
            document.format_risk_level
            if document.format_risk_level and document.format_risk_level != Document.FormatRisk.UNKNOWN
            else detect_format_risk(document.source_file_name or document.file.name)
        )

    checksum_sha256 = ""
    if uploaded_file is not None:
        checksum_sha256 = calculate_file_sha256(uploaded_file)
    if not checksum_sha256 and document.file:
        checksum_sha256 = calculate_file_sha256(document.file)
    if not checksum_sha256 and document.file and getattr(document.file, "path", None):
        checksum_sha256 = calculate_sha256(document.file.path)
    if checksum_sha256:
        document.checksum_sha256 = checksum_sha256


@transaction.atomic
def create_document_from_uploaded_file(
    *,
    uploaded_file,
    department,
    folder=None,
    folder_name: str = "",
    subfolder_name: str = "",
    title: str = "",
    description: str = "",
    doc_type=None,
    doc_date=None,
    language: str = Document.Language.UNKNOWN,
    document_author: str = "",
    status: str = Document.Status.DRAFT,
    retention_category: str = "",
    retention_until=None,
    legal_hold: bool = False,
    source_system: str = "manual_upload",
    uploaded_by=None,
    request=None,
    run_ai: bool = True,
    parser=parse_document,
    text_extractor=extract_text_from_file,
    indexer=index_document,
    audit_metadata: dict | None = None,
):
    document = Document(
        organization=department.organization,
        department=department,
        title=title or os.path.splitext(os.path.basename(uploaded_file.name))[0][:255],
        description=description or "",
        doc_type=doc_type,
        doc_date=doc_date,
        language=language or Document.Language.UNKNOWN,
        document_author=document_author or "",
        status=status or Document.Status.DRAFT,
        retention_category=retention_category or "",
        retention_until=retention_until,
        legal_hold=legal_hold,
        source_system=source_system or "manual_upload",
        uploaded_by=uploaded_by,
        file=uploaded_file,
    )
    document.save()
    populate_document_preservation_metadata(document, uploaded_file)

    target_folder = get_or_create_folder_tree(
        department=department,
        parent_folder=folder,
        folder_name=folder_name,
        subfolder_name=subfolder_name,
    )
    if target_folder:
        document.folder = target_folder
    elif folder:
        document.folder = folder

    attach_document_to_folder(document=document, folder=document.folder)

    if document.file and getattr(document.file, "path", None):
        document.extracted_text = text_extractor(document.file.path) or ""

    ai_text = " ".join(
        filter(
            None,
            [
                document.title,
                document.description,
                document.extracted_text,
            ],
        )
    ).strip()
    if run_ai and ai_text:
        run_document_ai_processing(
            document=document,
            text=ai_text,
            user=uploaded_by,
            request=request,
            source=ProcessingJob.Source.UPLOAD,
            parser=parser,
        )

    document.save()
    version = document.create_version(uploaded_by=uploaded_by)
    indexer(document)

    if uploaded_by is not None:
        DocumentActivity.objects.create(
            user=uploaded_by,
            document=document,
            action=DocumentActivity.ACTION_UPLOADED,
        )

    metadata = {
        "department_id": document.department_id,
        "folder_id": document.folder_id,
        "status": document.status,
    }
    if audit_metadata:
        metadata.update(audit_metadata)
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_UPLOADED,
        request=request,
        user=uploaded_by,
        document=document,
        document_version=version,
        metadata=metadata,
    )

    return document, version
