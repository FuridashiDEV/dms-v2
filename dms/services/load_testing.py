from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from dms.models import Department, Document, DocumentType, DocumentVersion, Folder, Organization, ProcessingJob


LOAD_TEST_ORG_SLUG = "load-test-synthetic"
LOAD_TEST_ORG_NAME = "Synthetic Load Test Organization"
DEFAULT_SAFE_EXECUTE_LIMIT = 1000


@dataclass(frozen=True)
class LoadProfile:
    name: str
    document_count: int
    batch_size: int
    queue_jobs: int
    search_queries: int
    description: str


@dataclass(frozen=True)
class SyntheticDocumentSpec:
    sequence: int
    title: str
    filename: str
    document_type: str
    language: str
    counterparty: str
    subject: str
    amount_kzt: int
    doc_date: date
    extracted_text: str
    estimated_file_bytes: int
    ocr_noise: bool


LOAD_PROFILES: dict[str, LoadProfile] = {
    "10k": LoadProfile("10k", 10_000, 500, 1_000, 50, "Small enterprise archive dry-run profile."),
    "100k": LoadProfile("100k", 100_000, 1_000, 10_000, 100, "Large department archive dry-run profile."),
    "500k": LoadProfile("500k", 500_000, 2_000, 50_000, 250, "Multi-department historical archive dry-run profile."),
    "1m": LoadProfile("1m", 1_000_000, 5_000, 100_000, 500, "Million document archive dry-run profile."),
}

DOCUMENT_TYPE_NAMES = ["Договор", "Акт", "Счет", "Приложение", "Приказ"]
COUNTERPARTIES = [
    "ИП Фирма",
    "ТОО Инвижн Архив",
    "Qazaq Tools LLP",
    "ТОО Север Логистика",
    "Central Campus Services",
]
SUBJECTS = [
    "поставка инструментов",
    "обслуживание архивной платформы",
    "аренда офисного помещения",
    "академическая мобильность",
    "регламент хранения документов",
]
KAZAKH_LINES = [
    "Құжат электрондық мұрағатқа синтетикалық жүктеме сынағы үшін дайындалды.",
    "Тараптар деректердің құпиялылығын және сақтау мерзімдерін сақтайды.",
]
RUSSIAN_LINES = [
    "Документ создан автоматически для синтетического нагрузочного тестирования.",
    "Содержит деловые реквизиты, сумму, контрагента и предмет документа.",
]


def get_load_profile(name: str) -> LoadProfile:
    try:
        return LOAD_PROFILES[name.lower()]
    except KeyError as exc:
        available = ", ".join(sorted(LOAD_PROFILES))
        raise ValueError(f"Unknown load profile '{name}'. Available profiles: {available}.") from exc


def iter_synthetic_document_specs(
    count: int,
    *,
    start: int = 0,
    include_ocr_noise: bool = True,
) -> Iterable[SyntheticDocumentSpec]:
    for index in range(start, start + max(int(count), 0)):
        doc_type = DOCUMENT_TYPE_NAMES[index % len(DOCUMENT_TYPE_NAMES)]
        counterparty = COUNTERPARTIES[index % len(COUNTERPARTIES)]
        subject = SUBJECTS[index % len(SUBJECTS)]
        language = "kk" if index % 7 == 0 else "ru"
        amount = 250_000 + (index % 250) * 125_000
        doc_date = date(2024, 1, 1) + timedelta(days=index % 730)
        ocr_noise = include_ocr_noise and index % 5 == 0
        title = f"{doc_type} LT-{index + 1:07d}: {counterparty} - {subject}"
        base_lines = KAZAKH_LINES if language == "kk" else RUSSIAN_LINES
        text = "\n".join(
            [
                title,
                f"Контрагент: {counterparty}",
                f"Предмет: {subject}",
                f"Сумма: {amount:,} KZT".replace(",", " "),
                f"Дата: {doc_date.isoformat()}",
                *base_lines,
            ]
        )
        if ocr_noise:
            text = apply_ocr_noise(text)
        yield SyntheticDocumentSpec(
            sequence=index + 1,
            title=title[:255],
            filename=f"synthetic-load-{index + 1:07d}.txt",
            document_type=doc_type,
            language=language,
            counterparty=counterparty,
            subject=subject,
            amount_kzt=amount,
            doc_date=doc_date,
            extracted_text=text,
            estimated_file_bytes=max(len(text.encode("utf-8")), 1024),
            ocr_noise=ocr_noise,
        )


def apply_ocr_noise(value: str) -> str:
    replacements = str.maketrans(
        {
            "о": "0",
            "О": "0",
            "е": "ё",
            "а": "a",
            "і": "i",
        }
    )
    return value.translate(replacements)


def build_load_profile_report(
    *,
    profile_name: str,
    dry_run: bool,
    target_count: int | None = None,
    actual_created: int = 0,
    duration_seconds: float = 0,
    report_path: str = "",
) -> dict:
    profile = get_load_profile(profile_name)
    requested = max(int(target_count or profile.document_count), 0)
    estimated_storage_bytes = estimate_storage_bytes(requested)
    throughput = round(actual_created / duration_seconds, 2) if actual_created and duration_seconds > 0 else 0
    doc_type_distribution = {
        doc_type: requested // len(DOCUMENT_TYPE_NAMES) + (1 if index < requested % len(DOCUMENT_TYPE_NAMES) else 0)
        for index, doc_type in enumerate(DOCUMENT_TYPE_NAMES)
    }
    return {
        "generated_at": timezone.now().isoformat(),
        "profile": asdict(profile),
        "dry_run": dry_run,
        "requested_documents": requested,
        "actual_created_documents": actual_created,
        "duration_seconds": round(duration_seconds, 3),
        "observed_create_throughput_docs_per_second": throughput,
        "synthetic_data": {
            "real_documents_used": False,
            "languages": ["ru", "kk"],
            "document_types": DOCUMENT_TYPE_NAMES,
            "includes_ocr_like_noise": True,
            "doc_type_distribution": doc_type_distribution,
            "sample_documents": [asdict(spec) for spec in iter_synthetic_document_specs(min(requested, 5))],
        },
        "benchmark": {
            "upload_throughput": {
                "mode": "estimated" if dry_run else "observed",
                "target_documents": requested,
                "observed_docs_per_second": throughput,
            },
            "processing": {
                "text_extraction_estimated_ms_per_doc": 15,
                "ocr_queue_estimated_jobs": min(requested, profile.queue_jobs),
                "entity_extraction_estimated_ms_per_doc": 8,
                "embedding_estimated_ms_per_doc": 35,
                "qdrant_insert_estimated_ms_per_doc": 10,
            },
            "search": {
                "planned_queries": profile.search_queries,
                "latency_measurement": "foundation; run against seeded data in a controlled environment",
            },
            "queue_overload": {
                "planned_jobs": profile.queue_jobs,
                "checks": ["backlog_growth", "backpressure", "retry_behavior", "failed_jobs"],
                "heavy_execution_default": False,
            },
            "storage": {
                "estimated_bytes": estimated_storage_bytes,
                "estimated_mb": round(estimated_storage_bytes / 1024 / 1024, 2),
            },
        },
        "safety": {
            "default_mode": "dry-run",
            "requires_execute_flag_for_db_writes": True,
            "safe_execute_limit_without_allow_heavy": DEFAULT_SAFE_EXECUTE_LIMIT,
            "no_real_customer_documents": True,
        },
        "report_path": report_path,
    }


def estimate_storage_bytes(document_count: int) -> int:
    return max(int(document_count), 0) * 2048


@transaction.atomic
def create_synthetic_documents(
    *,
    count: int,
    batch_size: int,
    organization_slug: str = LOAD_TEST_ORG_SLUG,
    include_versions: bool = True,
) -> int:
    scope = ensure_load_test_scope(organization_slug=organization_slug)
    organization = scope["organization"]
    department = scope["department"]
    folder = scope["folder"]
    user = scope["user"]
    doc_types = scope["doc_types"]
    created = 0
    safe_batch_size = max(min(int(batch_size or 100), 5000), 1)

    for batch_start in range(0, max(int(count), 0), safe_batch_size):
        specs = list(iter_synthetic_document_specs(min(safe_batch_size, count - batch_start), start=batch_start))
        documents = [
            Document(
                organization=organization,
                department=department,
                folder=folder,
                doc_type=doc_types[spec.document_type],
                title=spec.title,
                doc_date=spec.doc_date,
                description=f"Synthetic load-testing document #{spec.sequence}.",
                language=Document.Language.KK if spec.language == "kk" else Document.Language.RU,
                document_author="Synthetic Load Generator",
                retention_category="Synthetic load test",
                status=Document.Status.APPROVED,
                file=f"load-test/{organization.slug}/{spec.filename}",
                source_file_name=spec.filename,
                mime_type="text/plain",
                checksum_sha256=hashlib.sha256(spec.extracted_text.encode("utf-8")).hexdigest(),
                source_system="synthetic-load-test",
                extracted_text=spec.extracted_text,
                uploaded_by=user,
            )
            for spec in specs
        ]
        documents = Document.objects.bulk_create(documents, batch_size=safe_batch_size)
        if include_versions:
            DocumentVersion.objects.bulk_create(
                [
                    DocumentVersion(
                        document=document,
                        organization=organization,
                        number=1,
                        title=document.title,
                        description=document.description,
                        status=document.status,
                        doc_type=document.doc_type,
                        doc_date=document.doc_date,
                        department=department,
                        folder=folder,
                        language=document.language,
                        document_author=document.document_author,
                        retention_category=document.retention_category,
                        extracted_text=document.extracted_text,
                        file=document.file.name,
                        source_file_name=document.source_file_name,
                        mime_type=document.mime_type,
                        checksum_sha256=document.checksum_sha256,
                        source_system=document.source_system,
                        uploaded_by=user,
                    )
                    for document in documents
                ],
                batch_size=safe_batch_size,
            )
        created += len(documents)
    return created


def ensure_load_test_scope(*, organization_slug: str = LOAD_TEST_ORG_SLUG) -> dict:
    user_model = get_user_model()
    organization, _ = Organization.objects.get_or_create(
        slug=organization_slug,
        defaults={"name": LOAD_TEST_ORG_NAME, "is_active": True},
    )
    department, _ = Department.objects.get_or_create(
        organization=organization,
        name="Synthetic Load Test Department",
    )
    folder, _ = Folder.objects.get_or_create(
        organization=organization,
        department=department,
        parent=None,
        name="Synthetic Load Test Archive",
    )
    user, _ = user_model.objects.get_or_create(
        username=f"{organization_slug}-runner",
        defaults={
            "role": user_model.Role.ADMIN,
            "department": department,
            "is_staff": False,
            "is_active": True,
        },
    )
    if user.department_id != department.id:
        user.department = department
        user.save(update_fields=["department"])
    doc_types = {
        name: DocumentType.objects.get_or_create(organization=organization, name=name)[0]
        for name in DOCUMENT_TYPE_NAMES
    }
    return {
        "organization": organization,
        "department": department,
        "folder": folder,
        "user": user,
        "doc_types": doc_types,
    }


def simulate_queue_overload(*, organization_slug: str = LOAD_TEST_ORG_SLUG, jobs: int, batch_size: int = 1000) -> int:
    scope = ensure_load_test_scope(organization_slug=organization_slug)
    document = (
        Document.objects.filter(organization=scope["organization"], source_system="synthetic-load-test")
        .order_by("id")
        .first()
    )
    if document is None:
        return 0
    created = 0
    safe_batch_size = max(min(int(batch_size or 100), 5000), 1)
    for batch_start in range(0, max(int(jobs), 0), safe_batch_size):
        size = min(safe_batch_size, jobs - batch_start)
        ProcessingJob.objects.bulk_create(
            [
                ProcessingJob(
                    organization=scope["organization"],
                    document=document,
                    created_by=scope["user"],
                    status=ProcessingJob.Status.PENDING,
                    source=ProcessingJob.Source.MANUAL,
                    pipeline_stage=ProcessingJob.Stage.REINDEX,
                    priority=9,
                    idempotency_key=f"load-test-{organization_slug}-{batch_start + index}",
                )
                for index in range(size)
            ],
            batch_size=safe_batch_size,
            ignore_conflicts=True,
        )
        created += size
    return created


def write_load_report(report: dict, path: str | Path | None = None) -> Path:
    import json

    if path is None:
        reports_dir = Path(settings.BASE_DIR) / "reports" / "load-testing"
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        path = reports_dir / f"{report['profile']['name']}_{timestamp}.json"
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(output_path)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return output_path


def run_load_profile(
    *,
    profile_name: str,
    dry_run: bool = True,
    limit: int | None = None,
    organization_slug: str = LOAD_TEST_ORG_SLUG,
    include_queue: bool = False,
    queue_jobs: int | None = None,
    batch_size: int | None = None,
) -> dict:
    profile = get_load_profile(profile_name)
    target_count = max(int(limit or profile.document_count), 0)
    started = time.perf_counter()
    created = 0
    queued = 0
    if not dry_run:
        created = create_synthetic_documents(
            count=target_count,
            batch_size=batch_size or profile.batch_size,
            organization_slug=organization_slug,
        )
        if include_queue:
            queued = simulate_queue_overload(
                organization_slug=organization_slug,
                jobs=max(int(queue_jobs if queue_jobs is not None else min(profile.queue_jobs, target_count)), 0),
                batch_size=batch_size or profile.batch_size,
            )
    duration = time.perf_counter() - started
    report = build_load_profile_report(
        profile_name=profile_name,
        dry_run=dry_run,
        target_count=target_count,
        actual_created=created,
        duration_seconds=duration,
    )
    report["actual_created_queue_jobs"] = queued
    report["organization_slug"] = organization_slug if not dry_run else ""
    return report
