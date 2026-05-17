from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from dms.models import Document, DocumentVersion, ProcessingJob
from dms.services.load_testing import (
    LOAD_PROFILES,
    create_synthetic_documents,
    iter_synthetic_document_specs,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="dms_stage43_load_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MillionScaleLoadTestingStage43Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Path(TEST_MEDIA_ROOT).mkdir(parents=True, exist_ok=True)

    def test_load_profiles_cover_required_scales(self):
        self.assertEqual(LOAD_PROFILES["10k"].document_count, 10_000)
        self.assertEqual(LOAD_PROFILES["100k"].document_count, 100_000)
        self.assertEqual(LOAD_PROFILES["500k"].document_count, 500_000)
        self.assertEqual(LOAD_PROFILES["1m"].document_count, 1_000_000)

    def test_synthetic_generator_uses_business_documents_languages_and_ocr_noise(self):
        specs = list(iter_synthetic_document_specs(12))
        doc_types = {spec.document_type for spec in specs}
        languages = {spec.language for spec in specs}

        self.assertIn("Договор", doc_types)
        self.assertIn("Акт", doc_types)
        self.assertIn("Счет", doc_types)
        self.assertIn("Приложение", doc_types)
        self.assertIn("Приказ", doc_types)
        self.assertIn("ru", languages)
        self.assertIn("kk", languages)
        self.assertTrue(any(spec.ocr_noise for spec in specs))
        self.assertTrue(all("Synthetic Load" not in spec.counterparty for spec in specs))

    def test_dry_run_command_writes_report_without_creating_documents(self):
        report_path = Path(TEST_MEDIA_ROOT) / "reports" / "load-10k.json"
        call_command("run_load_profile", "--profile", "10k", "--dry-run", "--report", str(report_path))

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["requested_documents"], 10_000)
        self.assertEqual(payload["actual_created_documents"], 0)
        self.assertFalse(payload["synthetic_data"]["real_documents_used"])
        self.assertEqual(Document.objects.count(), 0)

    def test_execute_mode_requires_small_limit_or_explicit_heavy_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("run_load_profile", "--profile", "10k", "--execute")

    def test_execute_mode_creates_synthetic_documents_and_versions_for_small_limit(self):
        created = create_synthetic_documents(count=7, batch_size=3, organization_slug="stage-43-execute")

        self.assertEqual(created, 7)
        self.assertEqual(Document.objects.filter(source_system="synthetic-load-test").count(), 7)
        self.assertEqual(DocumentVersion.objects.filter(source_system="synthetic-load-test").count(), 7)
        document = Document.objects.filter(source_system="synthetic-load-test").first()
        self.assertIsNotNone(document)
        self.assertIn("load-test/stage-43-execute/", document.file.name)
        self.assertIn("Контрагент:", document.extracted_text)

    def test_execute_command_can_create_queue_overload_foundation(self):
        report_path = Path(TEST_MEDIA_ROOT) / "reports" / "load-execute.json"
        call_command(
            "run_load_profile",
            "--profile",
            "10k",
            "--execute",
            "--limit",
            "3",
            "--include-queue",
            "--queue-jobs",
            "4",
            "--organization-slug",
            "stage-43-queue",
            "--report",
            str(report_path),
        )

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertFalse(payload["dry_run"])
        self.assertEqual(payload["actual_created_documents"], 3)
        self.assertEqual(payload["actual_created_queue_jobs"], 4)
        self.assertEqual(ProcessingJob.objects.filter(organization__slug="stage-43-queue").count(), 4)
