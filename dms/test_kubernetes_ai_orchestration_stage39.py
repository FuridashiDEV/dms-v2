from __future__ import annotations

import io
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from dms.models import ProcessingJob
from dms.services.processing_center import enqueue_processing_job
from dms.services.processing_roles import PROCESSING_ROLES
from dms.test_factories import make_document, make_org_context


class KubernetesAIOrchestrationStage39Tests(TestCase):
    def setUp(self):
        self.context = make_org_context(slug="stage-39")
        self.document = make_document(context=self.context, title="Stage 39 processing role document")

    def test_processing_role_drains_only_matching_stages(self):
        ai_job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.AI_PARSE,
            idempotency_key="stage-39-ai-parse",
        )
        ocr_job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.OCR,
            idempotency_key="stage-39-ocr",
        )

        stdout = io.StringIO()
        call_command("run_processing_role", "--role", "entity-worker", "--once", "--limit", "5", stdout=stdout)

        ai_job.refresh_from_db()
        ocr_job.refresh_from_db()
        self.assertEqual(ai_job.status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(ocr_job.status, ProcessingJob.Status.PENDING)
        self.assertIn("role=entity-worker", stdout.getvalue())

    def test_worker_healthcheck_validates_role_without_leaking_settings(self):
        stdout = io.StringIO()

        call_command("processing_role_healthcheck", "--role", "embedding-worker", "--skip-db", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("ok role=embedding-worker", output)
        self.assertNotIn("SECRET_KEY", output)
        self.assertNotIn("POSTGRES_PASSWORD", output)

    def test_all_required_processing_roles_are_declared(self):
        expected = {
            "scheduler",
            "ocr-worker",
            "embedding-worker",
            "entity-worker",
            "rerank-worker",
            "qdrant-index-worker",
            "notification-worker",
        }

        self.assertEqual(set(PROCESSING_ROLES), expected)

    def test_kubernetes_templates_cover_roles_resources_gpu_and_keda(self):
        root = Path(__file__).resolve().parent.parent / "deploy" / "k8s"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.yaml"))

        for role in PROCESSING_ROLES:
            self.assertIn(role, combined)
        self.assertIn("resources:", combined)
        self.assertIn("requests:", combined)
        self.assertIn("limits:", combined)
        self.assertIn("nvidia.com/gpu", combined)
        self.assertIn("keda.sh/v1alpha1", combined)
        self.assertIn("/health/", combined)
        self.assertIn("processing_role_healthcheck", combined)

    def test_kubernetes_templates_do_not_contain_real_secret_values(self):
        root = Path(__file__).resolve().parent.parent / "deploy" / "k8s"
        combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in root.glob("*.yaml"))

        self.assertIn("replace-with-kubernetes-secret-manager-value", combined)
        self.assertNotIn("django-insecure", combined)
        self.assertNotIn("12345678", combined)
        self.assertNotIn("sk-", combined)
