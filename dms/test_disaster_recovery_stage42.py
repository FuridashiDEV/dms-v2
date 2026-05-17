from __future__ import annotations

import io
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dms.models import ProcessingJob
from dms.services.disaster_recovery import (
    recover_stuck_processing_jobs,
    restart_processing_job,
)
from dms.services.processing_center import enqueue_processing_job
from dms.test_factories import make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage42_dr_media_")


@override_settings(
    MEDIA_ROOT=TEST_MEDIA_ROOT,
    HEALTH_CHECK_STORAGE=True,
    HEALTH_CHECK_QUEUE=True,
    HEALTH_CHECK_PROCESSING_WORKER=True,
    HEALTH_CHECK_QDRANT=False,
)
class DisasterRecoveryStage42Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.context = make_org_context(slug="stage-42")
        self.document = make_document(context=self.context, title="Stage 42 recovery document")

    def test_recover_stuck_job_returns_retryable_job_to_pending(self):
        job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.OCR,
            idempotency_key="stage-42-stuck-retry",
        )
        job.status = ProcessingJob.Status.RUNNING
        job.locked_at = timezone.now() - timedelta(minutes=60)
        job.lock_token = "lock-token-not-exposed"
        job.attempt_count = 1
        job.max_attempts = 3
        job.save(update_fields=["status", "locked_at", "lock_token", "attempt_count", "max_attempts"])

        results = recover_stuck_processing_jobs(older_than_minutes=30)
        job.refresh_from_db()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action, "retry")
        self.assertEqual(job.status, ProcessingJob.Status.PENDING)
        self.assertEqual(job.lock_token, "")
        self.assertIsNone(job.locked_at)
        self.assertIsNotNone(job.next_retry_at)

    def test_recover_stuck_job_moves_exhausted_job_to_dead_letter(self):
        job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.EMBEDDING,
            idempotency_key="stage-42-stuck-dead-letter",
        )
        job.status = ProcessingJob.Status.RUNNING
        job.locked_at = timezone.now() - timedelta(minutes=60)
        job.attempt_count = 3
        job.max_attempts = 3
        job.save(update_fields=["status", "locked_at", "attempt_count", "max_attempts"])

        results = recover_stuck_processing_jobs(older_than_minutes=30)
        job.refresh_from_db()

        self.assertEqual(results[0].action, "dead_letter")
        self.assertEqual(job.status, ProcessingJob.Status.DEAD_LETTER)
        self.assertIsNotNone(job.completed_at)

    def test_manual_restart_resets_dead_letter_job_for_reprocessing(self):
        job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.REINDEX,
            idempotency_key="stage-42-manual-restart",
        )
        job.status = ProcessingJob.Status.DEAD_LETTER
        job.attempt_count = 5
        job.max_attempts = 5
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "attempt_count", "max_attempts", "completed_at"])

        result = restart_processing_job(job)
        job.refresh_from_db()

        self.assertEqual(result.action, "manual_restart")
        self.assertEqual(job.status, ProcessingJob.Status.PENDING)
        self.assertEqual(job.attempt_count, 0)
        self.assertIsNone(job.completed_at)

    def test_recovery_command_dry_run_does_not_change_job(self):
        job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.TEXT_EXTRACTION,
            idempotency_key="stage-42-command-dry-run",
        )
        job.status = ProcessingJob.Status.RUNNING
        job.locked_at = timezone.now() - timedelta(minutes=60)
        job.save(update_fields=["status", "locked_at"])
        stdout = io.StringIO()

        call_command("recover_processing_jobs", "--older-than-minutes", "30", "--dry-run", stdout=stdout)
        job.refresh_from_db()

        self.assertEqual(job.status, ProcessingJob.Status.RUNNING)
        self.assertIn("dry-run", stdout.getvalue())

    def test_health_endpoint_includes_storage_queue_and_worker_without_secrets_or_paths(self):
        response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        checks = payload["checks"]
        self.assertEqual(checks["database"], "ok")
        self.assertEqual(checks["storage"]["status"], "ok")
        self.assertEqual(checks["queue"]["status"], "ok")
        self.assertEqual(checks["processing_worker"]["status"], "ok")

        raw_payload = response.content.decode("utf-8")
        self.assertNotIn(TEST_MEDIA_ROOT, raw_payload)
        self.assertNotIn("lock-token-not-exposed", raw_payload)
        self.assertNotIn("SECRET_KEY", raw_payload)
        self.assertNotIn("POSTGRES_PASSWORD", raw_payload)

    @override_settings(HEALTH_CHECK_QDRANT=True)
    def test_qdrant_health_check_reports_unavailable_without_exception_details(self):
        with patch("dms.services.disaster_recovery.check_qdrant_available", return_value={"status": "error"}):
            response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["qdrant"]["status"], "error")
        self.assertNotIn("Traceback", response.content.decode("utf-8"))
