import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    AuditEvent,
    Counterparty,
    CounterpartyContact,
    Department,
    Document,
    DocumentExchange,
    ExchangeEvent,
    ExchangeMessage,
    ExtractedField,
    Organization,
    ProcessingJob,
    User,
    WorkflowAction,
    WorkflowInstance,
    WorkflowStepTemplate,
    WorkflowTemplate,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_evidence_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class LegalEvidencePackageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Evidence department")
        self.other_organization = Organization.objects.create(name="Other Evidence Org", slug="other-evidence-org")
        self.other_department = Department.objects.create(
            name="Evidence other",
            organization=self.other_organization,
        )
        self.user = User.objects.create_user(
            username="evidence-user",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="evidence-outsider",
            password="password123",
            department=self.other_department,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Evidence contract",
            description="Evidence export source",
            file=SimpleUploadedFile("evidence.txt", b"evidence payload"),
            uploaded_by=self.user,
            checksum_sha256="abc123",
            source_file_name="evidence.txt",
            mime_type="text/plain",
        )
        self.version = self.document.create_version(uploaded_by=self.user)

    def _create_related_evidence_data(self):
        job = ProcessingJob.objects.create(
            organization=self.department.organization,
            document=self.document,
            created_by=self.user,
            status=ProcessingJob.Status.REVIEWED,
            source=ProcessingJob.Source.UPLOAD,
            extracted_text_length=42,
        )
        ExtractedField.objects.create(
            organization=self.department.organization,
            job=job,
            document=self.document,
            field_name="document_number",
            label="Document number",
            value="CN-001",
            confidence="0.95",
            status=ExtractedField.Status.CONFIRMED,
            reviewed_by=self.user,
        )

        template = WorkflowTemplate.objects.create(
            organization=self.department.organization,
            name="Evidence approval",
            created_by=self.user,
        )
        step = WorkflowStepTemplate.objects.create(
            template=template,
            order=1,
            name="Legal review",
            approver_user=self.user,
        )
        instance = WorkflowInstance.objects.create(
            organization=self.department.organization,
            document=self.document,
            template=template,
            current_step_template=step,
            started_by=self.user,
        )
        WorkflowAction.objects.create(
            organization=self.department.organization,
            instance=instance,
            document=self.document,
            step_template=step,
            actor=self.user,
            action_type=WorkflowAction.ActionType.START,
            comment="Workflow started",
        )

        counterparty = Counterparty.objects.create(
            organization=self.department.organization,
            name="Evidence LLP",
            email="legal@example.com",
            created_by=self.user,
        )
        contact = CounterpartyContact.objects.create(
            counterparty=counterparty,
            name="Legal Contact",
            email="contact@example.com",
            created_by=self.user,
        )
        exchange = DocumentExchange.objects.create(
            organization=self.department.organization,
            document=self.document,
            counterparty=counterparty,
            counterparty_contact=contact,
            direction=DocumentExchange.Direction.OUTGOING,
            status=DocumentExchange.Status.SENT,
            sent_by=self.user,
            token_hash="should-not-export-token-hash",
            token_hint="no-export",
            message="Please review",
        )
        ExchangeEvent.objects.create(
            organization=self.department.organization,
            exchange=exchange,
            document=self.document,
            event_type=ExchangeEvent.EventType.SENT,
            actor_name="Evidence User",
            actor_email="user@example.com",
            comment="Sent for review",
        )
        ExchangeMessage.objects.create(
            organization=self.department.organization,
            exchange=exchange,
            document=self.document,
            counterparty=counterparty,
            counterparty_contact=contact,
            user=self.user,
            author_type=ExchangeMessage.AuthorType.INTERNAL,
            body="Internal evidence message",
        )
        AuditEvent.objects.create(
            organization=self.department.organization,
            user=self.user,
            document=self.document,
            event_type=AuditEvent.EventType.EXCHANGE_SENT,
            metadata={
                "portal_url": "https://example.test/portal/exchanges/super-secret-token/",
                "token_hash": "should-not-export-token-hash",
                "visible_note": "keep me",
            },
        )

    def test_evidence_export_includes_existing_sections_and_redacts_sensitive_values(self):
        self._create_related_evidence_data()
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:document_evidence_export", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("document-", response["Content-Disposition"])
        payload = json.loads(response.content)
        self.assertEqual(payload["schema"]["name"], "dms.legal_evidence_package")
        self.assertEqual(payload["organization"]["id"], self.department.organization_id)
        self.assertEqual(payload["document"]["id"], self.document.id)
        self.assertEqual(payload["document"]["checksum_sha256"], "abc123")
        self.assertEqual(payload["versions"][0]["number"], 1)
        self.assertEqual(payload["ai"]["fields"][0]["field_name"], "document_number")
        self.assertEqual(payload["workflow"][0]["actions"][0]["action_type"], WorkflowAction.ActionType.START)
        self.assertEqual(payload["exchanges"][0]["messages"][0]["body"], "Internal evidence message")
        self.assertEqual(payload["audit_events"][0]["metadata"]["visible_note"], "keep me")

        raw_payload = response.content.decode("utf-8")
        self.assertNotIn("super-secret-token", raw_payload)
        self.assertNotIn("should-not-export-token-hash", raw_payload)
        self.assertNotIn("token_hint", raw_payload)
        self.assertNotIn("token_hash", raw_payload)
        self.assertNotIn("raw_result", raw_payload)

    def test_evidence_export_records_audit_event(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:document_evidence_export", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.DOCUMENT_DOWNLOADED,
                metadata__evidence_exported=True,
                metadata__evidence_event_name="evidence.exported",
            ).exists()
        )

    def test_outsider_cannot_export_evidence_package(self):
        self.client.force_login(self.outsider)

        response = self.client.get(reverse("dms:document_evidence_export", args=[self.document.id]))

        self.assertEqual(response.status_code, 404)

    def test_evidence_export_excludes_cross_organization_audit_rows(self):
        AuditEvent.objects.create(
            organization=self.other_department.organization,
            user=self.outsider,
            document=self.document,
            event_type=AuditEvent.EventType.DOCUMENT_VIEWED,
            metadata={"visible_note": "foreign org row"},
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:document_evidence_export", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        raw_payload = response.content.decode("utf-8")
        self.assertNotIn("foreign org row", raw_payload)

    def test_authorized_user_can_open_human_readable_evidence_report(self):
        self._create_related_evidence_data()
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:document_evidence_report", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Доказательный отчёт")
        self.assertContains(response, "Документ")
        self.assertContains(response, "Версии")
        self.assertContains(response, "AI-поля")
        self.assertContains(response, "Согласование")
        self.assertContains(response, "Обмен и сообщения")
        self.assertContains(response, "События аудита")
        self.assertContains(response, "Хронология")
        self.assertContains(response, "Контрольная сумма")
        self.assertContains(response, "abc123")

    def test_outsider_cannot_open_human_readable_evidence_report(self):
        self.client.force_login(self.outsider)

        response = self.client.get(reverse("dms:document_evidence_report", args=[self.document.id]))

        self.assertEqual(response.status_code, 404)

    def test_human_readable_evidence_report_redacts_sensitive_values(self):
        self._create_related_evidence_data()
        AuditEvent.objects.create(
            organization=self.department.organization,
            user=self.user,
            document=self.document,
            event_type=AuditEvent.EventType.DOCUMENT_VIEWED,
            metadata={
                "server_path": "C:/private/storage/evidence.txt",
                "webhook_secret": "whsec_hidden",
                "visible_note": "human report note",
            },
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dms:document_evidence_report", args=[self.document.id]))

        self.assertEqual(response.status_code, 200)
        raw_report = response.content.decode("utf-8")
        self.assertIn("human report note", raw_report)
        self.assertNotIn("super-secret-token", raw_report)
        self.assertNotIn("should-not-export-token-hash", raw_report)
        self.assertNotIn("token_hint", raw_report)
        self.assertNotIn("token_hash", raw_report)
        self.assertNotIn("whsec_hidden", raw_report)
        self.assertNotIn("C:/private/storage", raw_report)
