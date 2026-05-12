from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet

from dms.models import AuditEvent, Document, DocumentRelation, UsageEvent
from dms.services.audit import record_audit_event
from dms.services.usage import record_usage_event
from dms.utils import get_allowed_documents, user_can_access_document


@dataclass(frozen=True)
class VisibleDocumentRelations:
    outgoing: QuerySet[DocumentRelation]
    incoming: QuerySet[DocumentRelation]


def get_relation_target_queryset(*, user, document: Document) -> QuerySet[Document]:
    return (
        get_allowed_documents(user)
        .filter(organization=document.organization)
        .exclude(pk=document.pk)
        .select_related("department", "doc_type")
        .order_by("-doc_date", "-created_at", "title")
    )


def get_visible_document_relations(*, user, document: Document) -> VisibleDocumentRelations:
    visible_document_ids = get_allowed_documents(user).filter(
        organization=document.organization,
    ).values("id")
    base_qs = DocumentRelation.objects.select_related(
        "from_document",
        "from_document__department",
        "from_document__doc_type",
        "to_document",
        "to_document__department",
        "to_document__doc_type",
    )
    return VisibleDocumentRelations(
        outgoing=base_qs.filter(
            from_document=document,
            to_document_id__in=visible_document_ids,
            to_document__organization=document.organization,
        ).order_by("relation_type", "-created_at", "-id"),
        incoming=base_qs.filter(
            to_document=document,
            from_document_id__in=visible_document_ids,
            from_document__organization=document.organization,
        ).order_by("relation_type", "-created_at", "-id"),
    )


def can_manage_document_relations(*, user, document: Document) -> bool:
    if not user_can_access_document(user, document):
        return False
    if user.role == "ADMIN":
        return True
    if document.uploaded_by_id == user.id:
        return True
    return bool(user.department_id and document.department_id == user.department_id)


def _assert_link_allowed(*, user, from_document: Document, to_document: Document) -> None:
    if from_document.pk == to_document.pk:
        raise ValidationError("A document cannot be related to itself.")
    if from_document.organization_id != to_document.organization_id:
        raise PermissionDenied("Cannot relate documents from different organizations.")
    if not user_can_access_document(user, from_document):
        raise PermissionDenied("No access to the source document.")
    if not user_can_access_document(user, to_document):
        raise PermissionDenied("No access to the related document.")
    if not can_manage_document_relations(user=user, document=from_document):
        raise PermissionDenied("No permission to manage document relations.")


@transaction.atomic
def create_document_relation(
    *,
    user,
    from_document: Document,
    to_document: Document,
    relation_type: str,
    request=None,
) -> tuple[DocumentRelation, bool]:
    _assert_link_allowed(user=user, from_document=from_document, to_document=to_document)
    relation, created = DocumentRelation.objects.get_or_create(
        from_document=from_document,
        to_document=to_document,
        relation_type=relation_type,
        defaults={"confidence": None},
    )
    if created:
        metadata = {
            "related_document_id": to_document.id,
            "related_document_title": to_document.title,
            "relation_type": relation_type,
            "relation_id": relation.id,
        }
        record_audit_event(
            event_type=AuditEvent.EventType.DOCUMENT_RELATION_CREATED,
            request=request,
            user=user,
            document=from_document,
            organization=from_document.organization,
            metadata=metadata,
        )
        record_usage_event(
            event_type=UsageEvent.EventType.DOCUMENT_RELATION_CREATED,
            user=user,
            document=from_document,
            source="document_relation",
            metadata=metadata,
        )
    return relation, created


@transaction.atomic
def delete_document_relation(*, user, relation: DocumentRelation, current_document: Document, request=None) -> None:
    if current_document.pk not in {relation.from_document_id, relation.to_document_id}:
        raise PermissionDenied("Relation does not belong to this document.")
    _assert_link_allowed(
        user=user,
        from_document=relation.from_document,
        to_document=relation.to_document,
    )
    if not can_manage_document_relations(user=user, document=current_document):
        raise PermissionDenied("No permission to delete this document relation.")

    metadata = {
        "related_document_id": (
            relation.to_document_id
            if current_document.pk == relation.from_document_id
            else relation.from_document_id
        ),
        "relation_type": relation.relation_type,
        "relation_id": relation.id,
    }
    source_document = relation.from_document
    relation.delete()
    record_audit_event(
        event_type=AuditEvent.EventType.DOCUMENT_RELATION_DELETED,
        request=request,
        user=user,
        document=source_document,
        organization=source_document.organization,
        metadata=metadata,
    )
    record_usage_event(
        event_type=UsageEvent.EventType.DOCUMENT_RELATION_DELETED,
        user=user,
        document=source_document,
        source="document_relation",
        metadata=metadata,
    )


def relation_visible_to_user_filter(*, user, document: Document) -> Q:
    visible_document_ids = get_allowed_documents(user).filter(
        organization=document.organization,
    ).values("id")
    return (
        Q(from_document=document, to_document_id__in=visible_document_ids)
        | Q(to_document=document, from_document_id__in=visible_document_ids)
    )
