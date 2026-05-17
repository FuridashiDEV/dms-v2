from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from dms.models import ProcessingJob, ProcessingProfile
from dms.services.processing_center import (
    build_processing_payload_snapshot,
    claim_next_processing_job,
    drain_processing_queue,
    enqueue_processing_job,
    fan_in_processing_job,
    fan_out_processing_job,
    get_backpressure_state,
)
from dms.test_factories import make_document, make_org_context


class ProcessingCenterStage38Tests(TestCase):
    def setUp(self):
        self.context = make_org_context(slug="stage-38")
        self.document = make_document(context=self.context, title="Stage 38 contract")

    def test_enqueue_uses_profile_and_idempotency(self):
        first_job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.ENTITY_EXTRACTION,
            user=self.context.user,
            idempotency_key="doc-entity-v1",
        )
        second_job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.ENTITY_EXTRACTION,
            user=self.context.user,
            idempotency_key="doc-entity-v1",
        )

        self.assertEqual(first_job.id, second_job.id)
        self.assertEqual(first_job.status, ProcessingJob.Status.PENDING)
        self.assertEqual(first_job.profile.organization, self.context.organization)
        self.assertEqual(first_job.pipeline_stage, ProcessingJob.Stage.ENTITY_EXTRACTION)
        self.assertEqual(ProcessingJob.objects.count(), 1)

    def test_backpressure_blocks_claim_when_profile_is_at_capacity(self):
        profile = ProcessingProfile.objects.create(
            organization=self.context.organization,
            name="Single worker",
            code="single-worker",
            max_concurrent_jobs=1,
            allowed_stages=[ProcessingJob.Stage.AI_PARSE],
        )
        enqueue_processing_job(document=self.document, profile=profile)
        ProcessingJob.objects.create(
            organization=self.context.organization,
            document=self.document,
            profile=profile,
            status=ProcessingJob.Status.RUNNING,
            pipeline_stage=ProcessingJob.Stage.AI_PARSE,
        )

        state = get_backpressure_state(profile=profile, organization=self.context.organization)
        claimed = claim_next_processing_job(profile=profile, organization=self.context.organization)

        self.assertFalse(state.available)
        self.assertEqual(state.reason, "max_concurrent_jobs_reached")
        self.assertIsNone(claimed)

    def test_retry_reschedules_then_fails_after_max_attempts(self):
        profile = ProcessingProfile.objects.create(
            organization=self.context.organization,
            name="Retry profile",
            code="retry-profile",
            max_concurrent_jobs=1,
            max_attempts=2,
            retry_backoff_seconds=1,
            allowed_stages=[ProcessingJob.Stage.AI_PARSE],
        )
        enqueue_processing_job(document=self.document, profile=profile)

        def failing_handler(_job):
            raise RuntimeError("temporary parser failure")

        first_results = drain_processing_queue(
            limit=1,
            profile=profile,
            organization=self.context.organization,
            handlers={ProcessingJob.Stage.AI_PARSE: failing_handler},
        )
        job = first_results[0].job
        job.refresh_from_db()

        self.assertEqual(job.status, ProcessingJob.Status.PENDING)
        self.assertEqual(job.attempt_count, 1)
        self.assertIsNotNone(job.next_retry_at)

        job.next_retry_at = timezone.now() - timedelta(seconds=1)
        job.scheduled_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["next_retry_at", "scheduled_at"])

        second_results = drain_processing_queue(
            limit=1,
            profile=profile,
            organization=self.context.organization,
            handlers={ProcessingJob.Stage.AI_PARSE: failing_handler},
        )
        job = second_results[0].job
        job.refresh_from_db()

        self.assertEqual(job.status, ProcessingJob.Status.FAILED)
        self.assertEqual(job.attempt_count, 2)
        self.assertIn("temporary parser failure", job.error_message)

    def test_fan_out_and_fan_in_complete_parent_after_children_complete(self):
        parent = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.FAN_OUT,
            idempotency_key="parent-stage-38",
        )
        children = fan_out_processing_job(
            parent_job=parent,
            stages=[ProcessingJob.Stage.TEXT_EXTRACTION, ProcessingJob.Stage.EMBEDDING],
            user=self.context.user,
        )

        self.assertEqual(len(children), 2)
        parent.refresh_from_db()
        self.assertEqual(parent.pipeline_stage, ProcessingJob.Stage.FAN_OUT)

        for child in children:
            child.status = ProcessingJob.Status.COMPLETED
            child.completed_at = timezone.now()
            child.save(update_fields=["status", "completed_at"])

        parent = fan_in_processing_job(parent, user=self.context.user)

        self.assertEqual(parent.status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(parent.pipeline_stage, ProcessingJob.Stage.FAN_IN)
        self.assertEqual(set(parent.raw_result["child_job_ids"]), {child.id for child in children})

    def test_reindex_handler_uses_existing_index_document_service(self):
        job = enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.REINDEX,
            idempotency_key="reindex-stage-38",
        )

        with patch("dms.services.document_indexing.index_document") as mocked_index:
            results = drain_processing_queue(
                limit=1,
                profile=job.profile,
                organization=self.context.organization,
            )

        job.refresh_from_db()
        self.assertEqual(results[0].status, ProcessingJob.Status.COMPLETED)
        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)
        mocked_index.assert_called_once_with(self.document)

    def test_payload_snapshot_does_not_include_file_path_or_raw_document_content(self):
        payload = build_processing_payload_snapshot(self.document)
        payload_text = str(payload).lower()

        self.assertIn("document", payload)
        self.assertIn("has_file", payload["document"])
        self.assertNotIn("path", payload_text)
        self.assertNotIn("qa payload", payload_text)

    def test_process_ai_queue_command_drains_foundation_queue(self):
        enqueue_processing_job(
            document=self.document,
            stage=ProcessingJob.Stage.AI_PARSE,
            idempotency_key="command-stage-38",
        )

        call_command(
            "process_ai_queue",
            "--limit",
            "1",
            "--organization-id",
            str(self.context.organization.id),
        )

        job = ProcessingJob.objects.get(idempotency_key="command-stage-38")
        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)
