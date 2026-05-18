from __future__ import annotations

import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import Department, DocumentRelation, DocumentType
from dms.services.document_relations import (
    build_document_relation_graph,
    create_document_relation,
    suggest_document_relations,
)
from dms.services.search_experience import accessible_related_documents_for_search
from dms.test_factories import make_document, make_org_context
from dms.utils import get_allowed_documents


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage45_relation_graph_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AdvancedDocumentRelationGraphStage45Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.context = make_org_context(slug="stage-45", username="stage-45-user")
        self.other_context = make_org_context(slug="stage-45-other", username="stage-45-other-user")
        self.contract_type = DocumentType.objects.create(organization=self.context.organization, name="Договор")
        self.appendix_type = DocumentType.objects.create(organization=self.context.organization, name="Приложение")
        self.act_type = DocumentType.objects.create(organization=self.context.organization, name="Акт")
        self.invoice_type = DocumentType.objects.create(organization=self.context.organization, name="Счет")

        self.contract = make_document(context=self.context, title="Contract tools supply project Alpha")
        self.contract.doc_type = self.contract_type
        self.contract.search_entities = {"counterparty": "ip firma"}
        self.contract.extracted_text = "Project Alpha contract with IP Firma for tools supply."
        self.contract.save(update_fields=["doc_type", "search_entities", "extracted_text"])

        self.appendix = make_document(context=self.context, title="Appendix A tools specification")
        self.appendix.doc_type = self.appendix_type
        self.appendix.search_entities = {"counterparty": "ip firma"}
        self.appendix.extracted_text = "Appendix for Project Alpha tools specification."
        self.appendix.save(update_fields=["doc_type", "search_entities", "extracted_text"])

        self.act = make_document(context=self.context, title="Act Project Alpha delivery")
        self.act.doc_type = self.act_type
        self.act.search_entities = {"counterparty": "ip firma"}
        self.act.extracted_text = "Act for Project Alpha delivery under contract."
        self.act.save(update_fields=["doc_type", "search_entities", "extracted_text"])

        self.invoice = make_document(context=self.context, title="Invoice Project Alpha payment")
        self.invoice.doc_type = self.invoice_type
        self.invoice.search_entities = {"counterparty": "ip firma"}
        self.invoice.extracted_text = "Invoice for Project Alpha payment."
        self.invoice.save(update_fields=["doc_type", "search_entities", "extracted_text"])

    def test_manual_relation_records_source_confirmation_and_creator(self):
        relation, created = create_document_relation(
            user=self.context.user,
            from_document=self.contract,
            to_document=self.appendix,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_APPENDIX,
        )

        self.assertTrue(created)
        self.assertEqual(relation.source, DocumentRelation.Source.MANUAL)
        self.assertTrue(relation.is_confirmed)
        self.assertEqual(relation.created_by, self.context.user)

    def test_relation_suggestions_are_not_auto_confirmed_or_persisted(self):
        suggestions = suggest_document_relations(
            user=self.context.user,
            document=self.contract,
            allowed_queryset=get_allowed_documents(self.context.user),
        )

        self.assertTrue(any(item.relation_type == DocumentRelation.RelationType.CONTRACT_TO_APPENDIX for item in suggestions))
        self.assertTrue(all(item.source == DocumentRelation.Source.SYSTEM_SUGGESTION for item in suggestions))
        self.assertTrue(all(item.confidence > 0 for item in suggestions))
        self.assertFalse(DocumentRelation.objects.exists())

    def test_relation_graph_builds_accessible_chain_and_hides_inaccessible_documents(self):
        DocumentRelation.objects.create(
            from_document=self.contract,
            to_document=self.appendix,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_APPENDIX,
            source=DocumentRelation.Source.MANUAL,
            is_confirmed=True,
            created_by=self.context.user,
        )
        DocumentRelation.objects.create(
            from_document=self.appendix,
            to_document=self.act,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_ACT,
            source=DocumentRelation.Source.MANUAL,
            is_confirmed=True,
            created_by=self.context.user,
        )
        DocumentRelation.objects.create(
            from_document=self.act,
            to_document=self.invoice,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_INVOICE,
            source=DocumentRelation.Source.MANUAL,
            is_confirmed=True,
            created_by=self.context.user,
        )
        private_department = Department.objects.create(
            organization=self.context.organization,
            name="Private Stage 45",
        )
        hidden = make_document(context=self.context, title="Hidden Project Alpha invoice")
        hidden.department = private_department
        hidden.save(update_fields=["department"])
        DocumentRelation.objects.create(
            from_document=self.contract,
            to_document=hidden,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_INVOICE,
        )

        graph = build_document_relation_graph(user=self.context.user, document=self.contract)

        node_titles = {node["title"] for node in graph.nodes}
        self.assertIn(self.contract.title, node_titles)
        self.assertIn(self.appendix.title, node_titles)
        self.assertIn(self.act.title, node_titles)
        self.assertIn(self.invoice.title, node_titles)
        self.assertNotIn(hidden.title, node_titles)
        self.assertTrue(any(len(chain) >= 4 for chain in graph.chains))

    def test_search_related_documents_use_only_confirmed_accessible_relations(self):
        DocumentRelation.objects.create(
            from_document=self.contract,
            to_document=self.appendix,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_APPENDIX,
            source=DocumentRelation.Source.AI_SUGGESTION,
            is_confirmed=False,
        )
        DocumentRelation.objects.create(
            from_document=self.contract,
            to_document=self.act,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_ACT,
            source=DocumentRelation.Source.MANUAL,
            is_confirmed=True,
        )

        related = accessible_related_documents_for_search(
            self.contract,
            get_allowed_documents(self.context.user),
        )
        titles = [item["document"].title for item in related]

        self.assertIn(self.act.title, titles)
        self.assertNotIn(self.appendix.title, titles)

    def test_document_detail_renders_graph_and_suggestions_without_confirming_them(self):
        self.client.force_login(self.context.user)
        DocumentRelation.objects.create(
            from_document=self.contract,
            to_document=self.appendix,
            relation_type=DocumentRelation.RelationType.CONTRACT_TO_APPENDIX,
            source=DocumentRelation.Source.MANUAL,
            is_confirmed=True,
        )

        response = self.client.get(reverse("dms:document_detail", args=[self.contract.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Граф связей")
        self.assertContains(response, "не подтверждено автоматически")
        self.assertEqual(DocumentRelation.objects.count(), 1)
