import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    ProcessingCostEstimate,
    ProcessingCostPolicy,
    ProcessingCostQuota,
    ProcessingJob,
    UsageEvent,
    User,
)
from dms.services.cost_optimization import (
    build_cost_dashboard_report,
    build_cost_quota_snapshot,
    create_processing_cost_estimate,
    ensure_default_cost_policies,
    ensure_default_cost_quotas,
    estimate_document_processing_cost,
    should_run_ocr,
)
from dms.services.processing_center import enqueue_processing_job
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage47_cost_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class CostOptimizationStage47Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-47-cost", username="stage-47-admin", role=User.Role.ADMIN)
        self.document = make_document(
            context=self.context,
            title="Cost controlled OCR contract",
            filename="cost-contract.pdf",
            content=b"x" * 260000,
            create_version=False,
        )
        self.document.extracted_text = "Contract text for OCR routing and embeddings. " * 50
        self.document.search_text_normalized = self.document.extracted_text.lower()
        self.document.save(update_fields=["extracted_text", "search_text_normalized"])

    def test_cost_estimation_includes_pages_chunks_policy_and_units(self):
        result = estimate_document_processing_cost(self.document, page_count=3, chunks_count=4)

        self.assertEqual(result.page_count, 3)
        self.assertEqual(result.chunks_count, 4)
        self.assertGreater(result.estimated_cost_units, 0)
        self.assertIn(
            result.recommended_policy,
            [choice for choice, _label in ProcessingCostPolicy.PolicyType.choices],
        )
        self.assertFalse(result.quota_snapshot["hard_enforcement"])

    def test_smart_ocr_routing_only_runs_when_needed(self):
        good = should_run_ocr(self.document)
        self.assertFalse(good.ocr_needed)
        self.assertEqual(good.reason, "text_available")

        self.document.extracted_text = ""
        self.document.save(update_fields=["extracted_text"])
        missing_text = should_run_ocr(self.document)

        self.assertTrue(missing_text.ocr_needed)
        self.assertEqual(missing_text.reason, "no_extracted_text")

    def test_create_estimate_records_report_only_usage_events(self):
        estimate = create_processing_cost_estimate(
            self.document,
            page_count=5,
            chunks_count=7,
            requested_ocr=True,
        )

        self.assertTrue(ProcessingCostEstimate.objects.filter(id=estimate.id).exists())
        self.assertTrue(
            UsageEvent.objects.filter(
                organization=self.context.organization,
                event_type=UsageEvent.EventType.AI_COST_UNIT,
            ).exists()
        )
        self.assertTrue(
            UsageEvent.objects.filter(
                organization=self.context.organization,
                event_type=UsageEvent.EventType.OCR_PAGE_PROCESSED,
                quantity=5,
            ).exists()
        )
        self.assertFalse(estimate.quota_snapshot["hard_enforcement"])

    def test_enqueue_processing_job_adds_cost_metadata_without_blocking(self):
        job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.OCR,
            user=self.context.user,
            idempotency_key="stage47-cost-job",
        )

        self.assertEqual(job.status, ProcessingJob.Status.PENDING)
        self.assertEqual(ProcessingJob.objects.count(), 1)
        self.assertTrue(ProcessingCostEstimate.objects.filter(processing_job=job).exists())
        self.assertEqual(job.center_metadata["cost_estimate"]["hard_enforcement"], False)

    def test_quota_foundation_warns_without_hard_enforcement(self):
        ensure_default_cost_quotas(self.context.organization)
        ProcessingCostQuota.objects.filter(
            organization=self.context.organization,
            quota_type=ProcessingCostQuota.QuotaType.COST_UNITS,
        ).update(monthly_limit=1, warning_percent=80)
        UsageEvent.objects.create(
            organization=self.context.organization,
            event_type=UsageEvent.EventType.AI_COST_UNIT,
            quantity=2,
        )

        snapshot = build_cost_quota_snapshot(self.context.organization)
        cost_row = next(row for row in snapshot["rows"] if row["quota_type"] == ProcessingCostQuota.QuotaType.COST_UNITS)

        self.assertEqual(cost_row["warning_level"], "exceeded")
        self.assertFalse(cost_row["hard_enforcement"])
        self.assertFalse(snapshot["hard_enforcement"])

    def test_cost_dashboard_report_and_view_are_admin_scoped(self):
        ensure_default_cost_policies(self.context.organization)
        create_processing_cost_estimate(self.document, page_count=2, chunks_count=3)

        report = build_cost_dashboard_report(self.context.organization)
        self.assertGreater(report["total_cost_units"], 0)
        self.assertFalse(report["hard_enforcement"])

        self.client.force_login(self.context.user)
        response = self.client.get(reverse("dms:cost_optimization_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cost optimization")
        self.assertEqual(response.context["selected_organization"], self.context.organization)

    def test_employee_cannot_open_cost_dashboard(self):
        employee_context = make_org_context(
            slug="stage-47-cost-employee",
            username="stage-47-employee",
            role=User.Role.EMPLOYEE,
        )
        self.client.force_login(employee_context.user)

        response = self.client.get(reverse("dms:cost_optimization_dashboard"))

        self.assertEqual(response.status_code, 403)
