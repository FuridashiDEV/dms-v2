from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dms.models import ObservabilityAlert, ObservabilityMetric, ProcessingJob
from dms.services.observability import (
    evaluate_observability_alerts,
    record_metric,
    record_processing_job_metric,
    record_search_latency,
)
from dms.test_factories import make_document, make_org_context


class EnterpriseObservabilityStage41Tests(TestCase):
    def setUp(self):
        self.context = make_org_context(slug="stage-41", role="ADMIN")
        self.other_context = make_org_context(slug="stage-41-other", role="ADMIN")
        self.document = make_document(context=self.context, title="Stage 41 contract")

    def test_metric_events_are_created_with_sanitized_labels(self):
        metric = record_metric(
            name="search.latency_ms",
            category=ObservabilityMetric.Category.SEARCH,
            value=123.4,
            organization=self.context.organization,
            unit="ms",
            labels={
                "mode": "hybrid",
                "api_token": "secret-token-value",
                "nested": {"password": "hidden", "safe": "visible"},
            },
        )

        self.assertEqual(metric.organization, self.context.organization)
        self.assertEqual(metric.value, 123.4)
        self.assertNotIn("api_token", metric.labels)
        self.assertNotIn("password", metric.labels["nested"])
        self.assertEqual(metric.labels["nested"]["safe"], "visible")
        self.assertNotIn("secret-token-value", str(metric.labels))

    def test_processing_metric_records_duration_without_document_content(self):
        job = ProcessingJob.objects.create(
            organization=self.context.organization,
            document=self.document,
            status=ProcessingJob.Status.COMPLETED,
            pipeline_stage=ProcessingJob.Stage.AI_PARSE,
            source=ProcessingJob.Source.MANUAL,
            started_at=timezone.now() - timedelta(seconds=2),
            completed_at=timezone.now(),
            error_message="parser failed on confidential text",
        )

        record_processing_job_metric(job, event="completed")

        labels_text = " ".join(str(metric.labels) for metric in ObservabilityMetric.objects.all())
        self.assertIn("AI_PARSE", labels_text)
        self.assertNotIn("confidential text", labels_text)
        self.assertTrue(ObservabilityMetric.objects.filter(name="job.duration_ms").exists())

    def test_search_latency_metric_is_organization_scoped(self):
        record_search_latency(
            organization_ids=[self.context.organization.id],
            latency_ms=42.5,
            degraded=False,
            result_count=3,
        )

        metric = ObservabilityMetric.objects.get(name="search.latency_ms")
        self.assertEqual(metric.organization, self.context.organization)
        self.assertEqual(metric.labels["result_count"], 3)
        self.assertFalse(metric.labels["degraded"])

    @override_settings(DMS_OBSERVABILITY_FAILED_JOBS_THRESHOLD=1)
    def test_failed_jobs_create_alert_foundation(self):
        ProcessingJob.objects.create(
            organization=self.context.organization,
            document=self.document,
            status=ProcessingJob.Status.FAILED,
            pipeline_stage=ProcessingJob.Stage.EMBEDDING,
            source=ProcessingJob.Source.MANUAL,
            completed_at=timezone.now(),
        )

        alerts = evaluate_observability_alerts(organizations=[self.context.organization])

        self.assertTrue(alerts)
        alert = ObservabilityAlert.objects.get(alert_type="processing.failed_jobs_high")
        self.assertEqual(alert.organization, self.context.organization)
        self.assertEqual(alert.status, ObservabilityAlert.Status.OPEN)
        self.assertNotIn("token", str(alert.details).lower())

    @override_settings(DMS_OBSERVABILITY_FAILED_JOBS_THRESHOLD=1)
    def test_dashboard_shows_own_metrics_and_not_other_org_metrics(self):
        ProcessingJob.objects.create(
            organization=self.context.organization,
            document=self.document,
            status=ProcessingJob.Status.FAILED,
            pipeline_stage=ProcessingJob.Stage.EMBEDDING,
            source=ProcessingJob.Source.MANUAL,
            completed_at=timezone.now(),
        )
        other_doc = make_document(context=self.other_context, title="Other observability document")
        ProcessingJob.objects.create(
            organization=self.other_context.organization,
            document=other_doc,
            status=ProcessingJob.Status.FAILED,
            pipeline_stage=ProcessingJob.Stage.OCR,
            source=ProcessingJob.Source.MANUAL,
            completed_at=timezone.now(),
        )
        self.client.force_login(self.context.user)

        response = self.client.get(reverse("dms:analytics_dashboard"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Наблюдаемость обработки и поиска", content)
        self.assertIn("Stage 41", content)
        self.assertNotIn("Stage 41 Other", content)

    @patch("dms.services.vector_store.ensure_collection", return_value=True)
    @patch("dms.services.vector_store.get_client")
    def test_vector_search_records_latency_without_payload_in_metric_labels(self, get_client_mock, _ensure_mock):
        point = Mock()
        point.id = "point-1"
        point.score = 0.9
        point.payload = {"document_id": self.document.id, "text_preview": "do not copy to metric"}
        get_client_mock.return_value.query_points.return_value.points = [point]

        from dms.services.vector_store import search_documents

        results = search_documents(
            embedding=[0.1] * 384,
            filters={"organization_id": [self.context.organization.id]},
        )

        self.assertEqual(len(results), 1)
        metric = ObservabilityMetric.objects.get(name="search.latency_ms")
        self.assertNotIn("text_preview", str(metric.labels))
        self.assertNotIn("do not copy", str(metric.labels))
