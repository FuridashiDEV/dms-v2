import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import AuditEvent, ProcessingJob, RetentionPolicy, SensitiveEntity
from dms.services.ai_processing import run_document_ai_processing
from dms.services.audit import record_audit_event
from dms.services.data_governance import (
    detect_sensitive_entities,
    ensure_default_retention_policies,
    sanitize_governance_metadata,
)
from dms.services.processing_center import enqueue_processing_job
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage46_governance_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EnterpriseSecurityDataGovernanceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-46-governance", username="stage-46-user")
        self.document = make_document(
            context=self.context,
            title="Contract with private identifier",
            filename="stage46.txt",
            create_version=False,
        )
        self.document.extracted_text = (
            "BIN 123456789012, email privacy@example.test, phone +7 701 123 45 67, "
            "FIO: Ivan Petrov, amount 3000000 KZT"
        )
        self.document.search_text_normalized = "contract private identifier"
        self.document.save(update_fields=["extracted_text", "search_text_normalized"])

    def test_sensitive_entity_detection_stores_masked_hashes_only(self):
        entities = detect_sensitive_entities(
            self.document.extracted_text,
            organization=self.context.organization,
            document=self.document,
            source="stage46-test",
            persist=True,
        )

        self.assertGreaterEqual(len(entities), 4)
        saved = SensitiveEntity.objects.filter(document=self.document)
        self.assertGreaterEqual(saved.count(), 4)
        stored_text = " ".join(f"{item.masked_value} {item.raw_value_hash}" for item in saved)
        self.assertNotIn("123456789012", stored_text)
        self.assertNotIn("privacy@example.test", stored_text)
        self.assertTrue(all(len(item.raw_value_hash) == 64 for item in saved))

    def test_audit_metadata_is_sanitized_before_storage(self):
        event = record_audit_event(
            event_type=AuditEvent.EventType.DOCUMENT_VIEWED,
            user=self.context.user,
            document=self.document,
            metadata={
                "query": "find privacy@example.test and 123456789012",
                "file_path": r"C:\private\document.pdf",
                "note": "phone +7 701 123 45 67",
                "token": "secret-token-value",
            },
        )

        payload = str(event.metadata)
        self.assertNotIn("privacy@example.test", payload)
        self.assertNotIn("123456789012", payload)
        self.assertNotIn("secret-token-value", payload)
        self.assertNotIn(r"C:\private\document.pdf", payload)
        self.assertIn("[redacted]", payload)

    @patch("dms.views.build_embedding", return_value=[])
    def test_search_audit_does_not_store_raw_query(self, _build_embedding_mock):
        self.client.force_login(self.context.user)

        response = self.client.get(
            reverse("dms:document_list"),
            {"q": "privacy@example.test 123456789012 contract"},
        )

        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.filter(event_type=AuditEvent.EventType.DOCUMENT_SEARCHED).latest("created_at")
        self.assertEqual(event.metadata["search_text_length"], len("privacy@example.test 123456789012 contract"))
        payload = str(event.metadata)
        self.assertNotIn("privacy@example.test", payload)
        self.assertNotIn("123456789012", payload)
        self.assertNotIn("privacy@example.test 123456789012 contract", payload)

    def test_ai_processing_detects_sensitive_entities_without_logging_full_text(self):
        def parser(**_kwargs):
            return {"title_ru": "Safe suggestion"}

        job = run_document_ai_processing(
            document=self.document,
            text=self.document.extracted_text,
            user=self.context.user,
            source=ProcessingJob.Source.MANUAL,
            parser=parser,
        )

        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)
        self.assertTrue(SensitiveEntity.objects.filter(document=self.document).exists())
        event = AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.AI_PROCESSING_COMPLETED,
            document=self.document,
        ).latest("created_at")
        self.assertIn("sensitive_entity_counts", event.metadata)
        self.assertNotIn("privacy@example.test", str(event.metadata))
        self.assertNotIn(self.document.extracted_text, str(event.metadata))

    def test_processing_center_metadata_uses_safe_payload_summary(self):
        job = enqueue_processing_job(
            document=self.document,
            user=self.context.user,
            payload={
                "file_path": r"C:\private\document.pdf",
                "full_text": self.document.extracted_text,
                "note": "privacy@example.test",
            },
        )

        payload = str(job.center_metadata)
        self.assertNotIn("Contract with private identifier", payload)
        self.assertNotIn("privacy@example.test", payload)
        self.assertNotIn(r"C:\private\document.pdf", payload)
        self.assertIn("payload_summary", job.center_metadata)

    def test_retention_policy_foundation_is_review_only(self):
        policies = ensure_default_retention_policies(self.context.organization)

        self.assertEqual(len(policies), 5)
        scopes = {policy.scope for policy in policies}
        self.assertIn(RetentionPolicy.Scope.DOCUMENT, scopes)
        self.assertTrue(all(policy.action == RetentionPolicy.Action.REVIEW_ONLY for policy in policies))
        self.assertTrue(RetentionPolicy.objects.filter(organization=self.context.organization).exists())

    def test_sanitize_governance_metadata_redacts_sensitive_keys_and_values(self):
        safe = sanitize_governance_metadata(
            {
                "authorization": "Bearer abc",
                "nested": {"raw_text": self.document.extracted_text},
                "comment": "email privacy@example.test",
            }
        )

        payload = str(safe)
        self.assertNotIn("Bearer abc", payload)
        self.assertNotIn("privacy@example.test", payload)
        self.assertNotIn(self.document.extracted_text, payload)
