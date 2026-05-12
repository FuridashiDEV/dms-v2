import json
import shutil
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import AuditEvent, Department, DocumentRelation, UsageEvent
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_related_docs_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class RelatedDocumentsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.context = make_org_context(slug="related-docs", username="related-user")
        self.other_context = make_org_context(slug="related-docs-other", username="related-other")
        self.document = make_document(
            context=self.context,
            title="Master contract",
            filename="master-contract.txt",
            content=b"master",
        )
        self.related_document = make_document(
            context=self.context,
            title="Appendix A",
            filename="appendix-a.txt",
            content=b"appendix",
        )
        self.cross_org_document = make_document(
            context=self.other_context,
            title="Foreign organization document",
            filename="foreign.txt",
            content=b"foreign",
        )

    @patch("dms.views.get_similar_documents_for_user", return_value=[])
    @patch("dms.views.build_document_ai_summary", return_value="")
    def test_user_can_link_accessible_documents_and_see_forward_and_reverse_links(
        self,
        _summary_mock,
        _similar_mock,
    ):
        self.client.force_login(self.context.user)

        response = self.client.post(
            reverse("dms:document_relation_add", args=[self.document.id]),
            {
                "to_document": self.related_document.id,
                "relation_type": DocumentRelation.RelationType.APPENDIX_TO,
            },
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        relation = DocumentRelation.objects.get(
            from_document=self.document,
            to_document=self.related_document,
        )
        self.assertEqual(relation.relation_type, DocumentRelation.RelationType.APPENDIX_TO)
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.DOCUMENT_RELATION_CREATED,
                metadata__related_document_id=self.related_document.id,
            ).exists()
        )
        self.assertTrue(
            UsageEvent.objects.filter(
                document=self.document,
                event_type=UsageEvent.EventType.DOCUMENT_RELATION_CREATED,
            ).exists()
        )

        detail_response = self.client.get(reverse("dms:document_detail", args=[self.document.id]))
        reverse_response = self.client.get(reverse("dms:document_detail", args=[self.related_document.id]))

        self.assertContains(detail_response, "Appendix A")
        self.assertContains(detail_response, "Remove relation")
        self.assertContains(reverse_response, "Master contract")

    def test_user_cannot_link_cross_organization_document(self):
        self.client.force_login(self.context.user)

        response = self.client.post(
            reverse("dms:document_relation_add", args=[self.document.id]),
            {
                "to_document": self.cross_org_document.id,
                "relation_type": DocumentRelation.RelationType.RELATED_TO,
            },
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        self.assertFalse(
            DocumentRelation.objects.filter(
                from_document=self.document,
                to_document=self.cross_org_document,
            ).exists()
        )

    def test_user_cannot_link_inaccessible_same_organization_document(self):
        private_department = Department.objects.create(
            organization=self.context.organization,
            name="Private department",
        )
        private_document = make_document(
            context=self.context,
            title="Private same tenant document",
            filename="private.txt",
            content=b"private",
        )
        private_document.department = private_department
        private_document.save(update_fields=["department"])
        self.client.force_login(self.context.user)

        response = self.client.post(
            reverse("dms:document_relation_add", args=[self.document.id]),
            {
                "to_document": private_document.id,
                "relation_type": DocumentRelation.RelationType.RELATED_TO,
            },
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        self.assertFalse(
            DocumentRelation.objects.filter(
                from_document=self.document,
                to_document=private_document,
            ).exists()
        )

    def test_delete_relation_records_audit_and_does_not_delete_documents(self):
        relation = DocumentRelation.objects.create(
            from_document=self.document,
            to_document=self.related_document,
            relation_type=DocumentRelation.RelationType.ACT,
        )
        self.client.force_login(self.context.user)

        response = self.client.post(
            reverse("dms:document_relation_delete", args=[self.document.id, relation.id])
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        self.assertFalse(DocumentRelation.objects.filter(pk=relation.pk).exists())
        self.assertTrue(type(self.document).objects.filter(pk=self.document.pk).exists())
        self.assertTrue(type(self.related_document).objects.filter(pk=self.related_document.pk).exists())
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.DOCUMENT_RELATION_DELETED,
                metadata__related_document_id=self.related_document.id,
            ).exists()
        )

    def test_evidence_export_includes_only_accessible_related_documents(self):
        DocumentRelation.objects.create(
            from_document=self.document,
            to_document=self.related_document,
            relation_type=DocumentRelation.RelationType.INVOICE,
        )
        DocumentRelation.objects.create(
            from_document=self.document,
            to_document=self.cross_org_document,
            relation_type=DocumentRelation.RelationType.RELATED_TO,
        )
        self.client.force_login(self.context.user)

        response = self.client.get(reverse("dms:document_evidence_export", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        related_titles = [
            item["related_document"]["title"]
            for item in payload["related_documents"]
        ]
        self.assertEqual(related_titles, ["Appendix A"])
        self.assertNotIn("Foreign organization document", response.content.decode("utf-8"))
