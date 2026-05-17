from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

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


@dataclass(frozen=True)
class RelationSuggestion:
    target: Document
    relation_type: str
    label: str
    source: str
    confidence: Decimal
    reasons: list[str]


@dataclass(frozen=True)
class RelationGraph:
    root_id: int
    nodes: list[dict]
    edges: list[dict]
    chains: list[list[dict]]


STAGE_45_RELATION_TYPES = {
    DocumentRelation.RelationType.CONTRACT_TO_APPENDIX,
    DocumentRelation.RelationType.CONTRACT_TO_INVOICE,
    DocumentRelation.RelationType.CONTRACT_TO_ACT,
    DocumentRelation.RelationType.CONTRACT_TO_ADDITIONAL_AGREEMENT,
    DocumentRelation.RelationType.PARENT_CHILD,
    DocumentRelation.RelationType.DUPLICATE,
    DocumentRelation.RelationType.REPLACES,
    DocumentRelation.RelationType.REFERENCES,
    DocumentRelation.RelationType.SAME_COUNTERPARTY,
    DocumentRelation.RelationType.SAME_PROJECT,
}

RELATION_GRAPH_CHAIN_TYPES = {
    DocumentRelation.RelationType.CONTRACT_TO_APPENDIX,
    DocumentRelation.RelationType.APPENDIX_TO,
    DocumentRelation.RelationType.CONTRACT_TO_ACT,
    DocumentRelation.RelationType.ACT,
    DocumentRelation.RelationType.CONTRACT_TO_INVOICE,
    DocumentRelation.RelationType.INVOICE,
    DocumentRelation.RelationType.CONTRACT_TO_ADDITIONAL_AGREEMENT,
    DocumentRelation.RelationType.ADDENDUM,
}


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


def build_document_relation_graph(
    *,
    user,
    document: Document,
    max_depth: int = 3,
    limit: int = 50,
) -> RelationGraph:
    allowed_ids = set(
        get_allowed_documents(user)
        .filter(organization=document.organization)
        .values_list("id", flat=True)
    )
    if document.id not in allowed_ids:
        return RelationGraph(root_id=document.id, nodes=[], edges=[], chains=[])

    relations = list(
        DocumentRelation.objects.filter(
            Q(from_document_id__in=allowed_ids) | Q(to_document_id__in=allowed_ids),
            from_document__organization=document.organization,
            to_document__organization=document.organization,
        )
        .select_related("from_document", "from_document__doc_type", "to_document", "to_document__doc_type", "created_by")
        .order_by("-is_confirmed", "-confidence", "-created_at", "-id")[: max(limit * 3, limit)]
    )

    adjacency: dict[int, list[DocumentRelation]] = {}
    by_id: dict[int, Document] = {document.id: document}
    for relation in relations:
        if relation.from_document_id not in allowed_ids or relation.to_document_id not in allowed_ids:
            continue
        adjacency.setdefault(relation.from_document_id, []).append(relation)
        adjacency.setdefault(relation.to_document_id, []).append(relation)
        by_id[relation.from_document_id] = relation.from_document
        by_id[relation.to_document_id] = relation.to_document

    visited = {document.id}
    queue: list[tuple[int, int]] = [(document.id, 0)]
    edge_ids: set[int] = set()
    while queue and len(visited) < limit:
        current_id, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for relation in adjacency.get(current_id, []):
            target_id = relation.to_document_id if relation.from_document_id == current_id else relation.from_document_id
            if target_id not in allowed_ids:
                continue
            edge_ids.add(relation.id)
            if target_id not in visited and len(visited) < limit:
                visited.add(target_id)
                queue.append((target_id, depth + 1))

    nodes = [_graph_node(by_id[document_id], is_root=document_id == document.id) for document_id in visited]
    edges = [_graph_edge(relation) for relation in relations if relation.id in edge_ids]
    return RelationGraph(
        root_id=document.id,
        nodes=sorted(nodes, key=lambda item: (not item["is_root"], item["title"])),
        edges=edges,
        chains=_build_relation_chains(document_id=document.id, edges=edges, nodes_by_id={node["id"]: node for node in nodes}),
    )


def suggest_document_relations(
    *,
    user,
    document: Document,
    allowed_queryset: QuerySet[Document],
    limit: int = 6,
) -> list[RelationSuggestion]:
    candidates = (
        allowed_queryset.filter(organization=document.organization)
        .exclude(pk=document.pk)
        .select_related("department", "doc_type")
        .order_by("-doc_date", "-created_at")[:100]
    )
    existing_pairs = set(
        DocumentRelation.objects.filter(Q(from_document=document) | Q(to_document=document)).values_list(
            "from_document_id",
            "to_document_id",
            "relation_type",
        )
    )
    suggestions: list[RelationSuggestion] = []
    for candidate in candidates:
        relation_type, confidence, reasons = infer_relation_type(document, candidate)
        if not relation_type or confidence < Decimal("0.45"):
            continue
        if (
            (document.id, candidate.id, relation_type) in existing_pairs
            or (candidate.id, document.id, relation_type) in existing_pairs
        ):
            continue
        suggestions.append(
            RelationSuggestion(
                target=candidate,
                relation_type=relation_type,
                label=_relation_suggestion_label(relation_type),
                source=DocumentRelation.Source.SYSTEM_SUGGESTION,
                confidence=confidence,
                reasons=reasons,
            )
        )
        if len(suggestions) >= limit:
            break
    suggestions.sort(key=lambda item: (item.confidence, item.target.doc_date or item.target.created_at.date()), reverse=True)
    return suggestions[:limit]


def infer_relation_type(source: Document, candidate: Document) -> tuple[str, Decimal, list[str]]:
    source_type = _document_type_text(source)
    candidate_type = _document_type_text(candidate)
    source_text = _document_relation_text(source)
    candidate_text = _document_relation_text(candidate)
    reasons: list[str] = []

    if source.checksum_sha256 and source.checksum_sha256 == candidate.checksum_sha256:
        return DocumentRelation.RelationType.DUPLICATE, Decimal("0.98"), ["same sha256 checksum"]

    if _has_any(source_type, "договор", "contract") and _has_any(candidate_type, "прилож", "appendix"):
        reasons.append("contract and appendix document types")
        return DocumentRelation.RelationType.CONTRACT_TO_APPENDIX, Decimal("0.86"), reasons
    if _has_any(source_type, "договор", "contract") and _has_any(candidate_type, "акт", "act"):
        reasons.append("contract and act document types")
        return DocumentRelation.RelationType.CONTRACT_TO_ACT, Decimal("0.82"), reasons
    if _has_any(source_type, "договор", "contract") and _has_any(candidate_type, "счет", "invoice"):
        reasons.append("contract and invoice document types")
        return DocumentRelation.RelationType.CONTRACT_TO_INVOICE, Decimal("0.82"), reasons
    if _has_any(source_type, "договор", "contract") and _has_any(candidate_type, "соглаш", "agreement", "доп"):
        reasons.append("contract and additional agreement document types")
        return DocumentRelation.RelationType.CONTRACT_TO_ADDITIONAL_AGREEMENT, Decimal("0.84"), reasons

    shared_counterparty = _shared_entity(source, candidate, "counterparty")
    if shared_counterparty:
        reasons.append(f"same counterparty: {shared_counterparty}")
        if _has_any(candidate_type, "акт", "act"):
            return DocumentRelation.RelationType.CONTRACT_TO_ACT, Decimal("0.68"), reasons
        if _has_any(candidate_type, "счет", "invoice"):
            return DocumentRelation.RelationType.CONTRACT_TO_INVOICE, Decimal("0.66"), reasons
        return DocumentRelation.RelationType.SAME_COUNTERPARTY, Decimal("0.62"), reasons

    shared_project = _shared_project_phrase(source_text, candidate_text)
    if shared_project:
        reasons.append(f"shared project phrase: {shared_project}")
        return DocumentRelation.RelationType.SAME_PROJECT, Decimal("0.58"), reasons

    if source.public_id and str(source.public_id) in candidate_text:
        return DocumentRelation.RelationType.REFERENCES, Decimal("0.64"), ["candidate references source public id"]
    if candidate.public_id and str(candidate.public_id) in source_text:
        return DocumentRelation.RelationType.REFERENCES, Decimal("0.64"), ["source references candidate public id"]

    return "", Decimal("0.00"), []


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
        defaults={
            "confidence": None,
            "source": DocumentRelation.Source.MANUAL,
            "is_confirmed": True,
            "created_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    if created:
        metadata = {
            "related_document_id": to_document.id,
            "related_document_title": to_document.title,
            "relation_type": relation_type,
            "relation_id": relation.id,
            "source": relation.source,
            "is_confirmed": relation.is_confirmed,
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


def _graph_node(document: Document, *, is_root: bool) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "document_type": document.doc_type.name if document.doc_type_id else "",
        "status": document.status,
        "doc_date": document.doc_date,
        "is_root": is_root,
    }


def _graph_edge(relation: DocumentRelation) -> dict:
    return {
        "id": relation.id,
        "from_id": relation.from_document_id,
        "to_id": relation.to_document_id,
        "relation_type": relation.relation_type,
        "label": relation.get_relation_type_display(),
        "source": relation.source,
        "confidence": relation.confidence,
        "is_confirmed": relation.is_confirmed,
        "created_by": relation.created_by.username if relation.created_by_id else "",
        "created_at": relation.created_at,
    }


def _build_relation_chains(*, document_id: int, edges: list[dict], nodes_by_id: dict[int, dict]) -> list[list[dict]]:
    outgoing = {}
    for edge in edges:
        if edge["relation_type"] in RELATION_GRAPH_CHAIN_TYPES:
            outgoing.setdefault(edge["from_id"], []).append(edge)

    chains = []
    for first_edge in outgoing.get(document_id, []):
        chain = [nodes_by_id[document_id], nodes_by_id[first_edge["to_id"]]]
        current_id = first_edge["to_id"]
        seen = {document_id, current_id}
        while len(chain) < 5:
            next_edge = next((edge for edge in outgoing.get(current_id, []) if edge["to_id"] not in seen), None)
            if next_edge is None:
                break
            current_id = next_edge["to_id"]
            seen.add(current_id)
            chain.append(nodes_by_id[current_id])
        if len(chain) > 1:
            chains.append(chain)
    return chains[:5]


def _document_type_text(document: Document) -> str:
    return " ".join(part.lower() for part in [document.doc_type.name if document.doc_type_id else "", document.title] if part)


def _document_relation_text(document: Document) -> str:
    return " ".join(
        part.lower()
        for part in [
            document.title,
            document.description,
            document.document_author,
            document.extracted_text[:1000] if document.extracted_text else "",
            str(document.search_entities or {}),
        ]
        if part
    )


def _has_any(value: str, *needles: str) -> bool:
    return any(needle.lower() in value for needle in needles)


def _shared_entity(source: Document, candidate: Document, key: str) -> str:
    source_value = str((source.search_entities or {}).get(key) or "").strip().lower()
    candidate_value = str((candidate.search_entities or {}).get(key) or "").strip().lower()
    if source_value and candidate_value and source_value == candidate_value:
        return source_value
    return ""


def _shared_project_phrase(source_text: str, candidate_text: str) -> str:
    markers = ("проект", "project", "договор", "contract")
    for marker in markers:
        source_index = source_text.find(marker)
        if source_index < 0:
            continue
        phrase = " ".join(source_text[source_index : source_index + 80].split()[:6])
        if len(phrase) >= 10 and phrase in candidate_text:
            return phrase
    return ""


def _relation_suggestion_label(relation_type: str) -> str:
    labels = {
        DocumentRelation.RelationType.CONTRACT_TO_APPENDIX: "Suggested appendix",
        DocumentRelation.RelationType.CONTRACT_TO_INVOICE: "Suggested invoice",
        DocumentRelation.RelationType.CONTRACT_TO_ACT: "Suggested act",
        DocumentRelation.RelationType.CONTRACT_TO_ADDITIONAL_AGREEMENT: "Suggested additional agreement",
        DocumentRelation.RelationType.DUPLICATE: "Possible duplicate",
        DocumentRelation.RelationType.SAME_COUNTERPARTY: "Same counterparty",
        DocumentRelation.RelationType.SAME_PROJECT: "Same project",
        DocumentRelation.RelationType.REFERENCES: "Reference",
    }
    return labels.get(relation_type, "Suggested relation")
