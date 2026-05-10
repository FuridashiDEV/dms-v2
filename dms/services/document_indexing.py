import logging

from dms.models import Document
from dms.services.embedding import build_embedding
from dms.services.vector_store import delete_document, upsert_document


logger = logging.getLogger(__name__)


def build_document_index_text(document: Document) -> str:
    return " ".join(
        filter(
            None,
            [
                document.title,
                document.description,
                document.extracted_text,
            ],
        )
    ).strip()


def build_document_index_payload(document: Document) -> dict:
    return {
        "title": document.title,
        "department_id": document.department_id,
        "folder_id": document.folder_id,
        "doc_type_id": document.doc_type_id,
        "doc_date": document.doc_date.isoformat() if document.doc_date else None,
    }


def index_document(document: Document) -> bool:
    vector = build_embedding(build_document_index_text(document))
    if not vector:
        return False

    try:
        return upsert_document(
            doc_id=document.id,
            vector=vector,
            payload=build_document_index_payload(document),
        )
    except Exception:
        logger.exception("Failed to index document", extra={"document_id": document.id})
        return False


def delete_document_from_index(document_id: int) -> bool:
    try:
        return delete_document(document_id)
    except Exception:
        logger.exception("Failed to delete document from vector index", extra={"document_id": document_id})
        return False
