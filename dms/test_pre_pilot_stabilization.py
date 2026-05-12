import json
import re
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    AuditEvent,
    Document,
    DocumentExchange,
    DocumentRelation,
    ExtractedField,
    UsageEvent,
    WorkflowInstance,
    WorkflowStepTemplate,
    WorkflowTemplate,
)
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_pre_pilot_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PrePilotDemoFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.context = make_org_context(slug="pre-pilot", username="pilot-admin", role="ADMIN")
        self.user = self.context.user
        self.related_document = make_document(
            context=self.context,
            title="Pilot appendix",
            filename="pilot-appendix.txt",
            content=b"appendix",
        )

    @patch("dms.views.index_document", return_value=False)
    @patch("dms.views.parse_document")
    @patch("dms.views.extract_text_from_file", return_value="Pilot contract text 2026-05-12")
    def test_pre_pilot_demo_flow_has_working_navigation_and_actions(
        self,
        _extract_text_mock,
        parse_document_mock,
        _index_document_mock,
    ):
        parse_document_mock.return_value = {
            "title_ru": "Pilot contract reviewed",
            "summary_ru": "Reviewed pilot metadata",
            "language": Document.Language.RU,
        }

        self.assertTrue(self.client.login(username=self.user.username, password="password123"))
        self.assertEqual(self.client.get(reverse("dms:dashboard")).status_code, 200)

        upload_response = self.client.post(
            reverse("dms:document_upload"),
            {
                "department": self.context.department.id,
                "title": "Pilot contract",
                "status": Document.Status.DRAFT,
                "language": Document.Language.UNKNOWN,
                "new_folder": "Pilot demo",
                "file": SimpleUploadedFile("pilot-contract.txt", b"pilot contract"),
            },
        )
        self.assertRedirects(upload_response, reverse("dms:document_list"))
        document = Document.objects.get(title="Pilot contract")

        self.assertEqual(self.client.get(reverse("dms:document_detail", args=[document.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dms:document_view", args=[document.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dms:document_download", args=[document.id])).status_code, 200)

        ai_review_response = self.client.get(reverse("dms:document_ai_review", args=[document.id]))
        self.assertEqual(ai_review_response.status_code, 200)
        field = document.extracted_fields.get(field_name="title")
        apply_response = self.client.post(
            reverse("dms:document_ai_review", args=[document.id]),
            {
                f"field_{field.id}": "Pilot contract reviewed",
                f"decision_{field.id}": "confirm",
                "action": "apply",
            },
        )
        self.assertRedirects(apply_response, reverse("dms:document_detail", args=[document.id]))
        document.refresh_from_db()
        self.assertEqual(document.title, "Pilot contract reviewed")
        self.assertEqual(field.__class__.objects.get(pk=field.pk).status, ExtractedField.Status.APPLIED)

        relation_response = self.client.post(
            reverse("dms:document_relation_add", args=[document.id]),
            {
                "to_document": self.related_document.id,
                "relation_type": DocumentRelation.RelationType.APPENDIX_TO,
            },
        )
        self.assertRedirects(relation_response, reverse("dms:document_detail", args=[document.id]))

        template = WorkflowTemplate.objects.create(
            organization=self.context.organization,
            name="Pilot approval",
            created_by=self.user,
        )
        WorkflowStepTemplate.objects.create(
            template=template,
            order=1,
            name="Pilot approver",
            approver_user=self.user,
        )
        workflow_start_response = self.client.post(
            reverse("dms:document_workflow_start", args=[document.id]),
            {"template": template.id, "comment": "Start pilot approval"},
        )
        self.assertRedirects(workflow_start_response, reverse("dms:document_detail", args=[document.id]))
        workflow = WorkflowInstance.objects.get(document=document)
        workflow_action_response = self.client.post(
            reverse("dms:document_workflow_action", args=[document.id, workflow.id, "approve"]),
            {"comment": "Approved for pilot"},
        )
        self.assertRedirects(workflow_action_response, reverse("dms:document_detail", args=[document.id]))

        exchange_response = self.client.post(
            reverse("dms:document_exchange_send", args=[document.id]),
            {
                "new_counterparty_name": "Pilot Counterparty LLP",
                "new_counterparty_email": "pilot-counterparty@example.test",
                "new_contact_name": "Pilot Reviewer",
                "new_contact_email": "reviewer@example.test",
                "message": "Please review the pilot document.",
                "business_document_type": DocumentExchange.BusinessDocumentType.CONTRACT,
                "expires_days": 7,
            },
        )
        self.assertEqual(exchange_response.status_code, 302)
        self.assertEqual(exchange_response["Location"], reverse("dms:document_detail", args=[document.id]))
        exchange = DocumentExchange.objects.get(document=document)
        portal_url = self.client.session[f"counterparty_exchange_url:{document.pk}"]
        token = re.search(r"/portal/exchanges/([^/]+)/", portal_url).group(1)

        self.assertEqual(self.client.get(reverse("dms:counterparty_portal", args=[token])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dms:counterparty_portal_download", args=[token])).status_code, 200)
        comment_response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[token, "comment"]),
            {"comment": "External pilot comment"},
        )
        self.assertRedirects(comment_response, reverse("dms:counterparty_portal", args=[token]))
        accept_response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[token, "accept"]),
            {"comment": "Accepted for pilot"},
        )
        self.assertRedirects(accept_response, reverse("dms:counterparty_portal", args=[token]))
        exchange.refresh_from_db()
        self.assertEqual(exchange.status, DocumentExchange.Status.ACCEPTED)

        evidence_response = self.client.get(reverse("dms:document_evidence_export", args=[document.id]))
        self.assertEqual(evidence_response.status_code, 200)
        evidence_payload = json.loads(evidence_response.content)
        self.assertEqual(evidence_payload["document"]["id"], document.id)
        self.assertEqual(evidence_payload["related_documents"][0]["related_document"]["id"], self.related_document.id)

        self.assertEqual(self.client.get(reverse("dms:usage_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dms:analytics_dashboard")).status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(document=document).exists())
        self.assertTrue(UsageEvent.objects.filter(document=document).exists())
