from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from dms.models import (
    Department,
    Document,
    DocumentAccess,
    DocumentActivity,
    DocumentRelation,
    DocumentType,
    Folder,
    OrganizationMember,
)
from dms.services.embedding import build_embedding
from dms.services.preservation import calculate_sha256, detect_format_risk, detect_mime_type
from dms.services.vector_store import COLLECTION_NAME, ensure_collection, get_client, upsert_document


User = get_user_model()


@dataclass
class DemoDoc:
    title: str
    file_name: str
    file_bytes: bytes
    department: Department
    folder: Folder
    doc_type: DocumentType
    description: str
    extracted_text: str
    doc_date: date
    author: str
    retention_category: str
    retention_until: date
    status: str = Document.Status.APPROVED
    language: str = Document.Language.RU
    legal_hold: bool = False
    source_system: str = "demo_seed"


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_simple_pdf(title: str, lines: list[str]) -> bytes:
    clean_lines = [_pdf_escape(title[:70])] + [_pdf_escape(line[:80]) for line in lines[:12]]
    text_stream = ["BT", "/F1 18 Tf", "50 760 Td", f"({_pdf_escape(title[:60])}) Tj", "/F1 11 Tf"]
    for index, line in enumerate(clean_lines[1:], start=1):
        y_shift = 24 if index == 1 else 18
        text_stream.append(f"0 -{y_shift} Td")
        text_stream.append(f"({line}) Tj")
    text_stream.append("ET")
    stream = "\n".join(text_stream).encode("latin-1", errors="replace")

    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj",
        b"4 0 obj << /Length %d >> stream\n%s\nendstream endobj" % (len(stream), stream),
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
        pdf.extend(b"\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(pdf)


class Command(BaseCommand):
    help = "Очищает старые данные и подготавливает красивый набор демо-данных для презентации."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Подготовка демо-данных началась..."))
        self._clear_existing_data()
        demo_context = self._seed_demo_data()
        self._seed_vectors(demo_context["documents"])
        self.stdout.write(self.style.SUCCESS("Демо-данные готовы."))
        self.stdout.write("Логины для демо:")
        for username, password in demo_context["credentials"]:
            self.stdout.write(f"  - {username} / {password}")

    def _clear_existing_data(self) -> None:
        self.stdout.write("Очистка старых документов, папок и пользователей...")

        Document.objects.all().delete()
        Folder.objects.all().delete()
        DocumentType.objects.all().delete()
        Department.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

        documents_dir = Path(settings.MEDIA_ROOT) / "documents"
        if documents_dir.exists():
            shutil.rmtree(documents_dir, ignore_errors=True)

        try:
            client = get_client()
            collections = {item.name for item in client.get_collections().collections}
            if COLLECTION_NAME in collections:
                client.delete_collection(COLLECTION_NAME)
            ensure_collection()
        except Exception:
            self.stdout.write(self.style.WARNING("Qdrant недоступен: вектора будут пропущены."))

    def _seed_demo_data(self) -> dict:
        self.stdout.write("Создание структуры архива и демо-документов...")

        demo_password = "DemoArchive2026!"
        demo_admin = User.objects.create_user(
            username="demo_admin",
            password=demo_password,
            first_name="Айжан",
            last_name="Серикова",
            role=User.Role.ADMIN,
            is_staff=True,
        )

        rectorate = Department.objects.create(name="Ректорат")
        legal = Department.objects.create(name="Юридический отдел")
        finance = Department.objects.create(name="Финансовый отдел")
        education = Department.objects.create(name="Учебный офис")
        archive = Department.objects.create(name="Архив")
        demo_organization = rectorate.organization
        OrganizationMember.objects.create(
            organization=demo_organization,
            user=demo_admin,
            role=OrganizationMember.Role.ADMIN,
        )

        demo_users = [
            ("legal_demo", "DemoArchive2026!", "Марат", "Оспанов", legal, "Юрисконсульт"),
            ("finance_demo", "DemoArchive2026!", "Дина", "Сатпаева", finance, "Финансовый аналитик"),
            ("study_demo", "DemoArchive2026!", "Алия", "Жаксылыкова", education, "Методист"),
            ("archive_demo", "DemoArchive2026!", "Ерлан", "Турсынов", archive, "Архивариус"),
        ]
        for username, password, first_name, last_name, department, position in demo_users:
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.EMPLOYEE,
                department=department,
                position=position,
            )
            OrganizationMember.objects.create(
                organization=department.organization,
                user=user,
                role=OrganizationMember.Role.MEMBER,
            )

        doc_types = {
            name: DocumentType.objects.create(name=name)
            for name in [
                "Приказ",
                "Положение",
                "Договор",
                "Приложение",
                "Бюджет",
                "Политика хранения",
                "Номенклатура дел",
                "Регламент",
            ]
        }

        folders = {
            "rect_orders": Folder.objects.create(name="Приказы", department=rectorate),
            "edu_process": Folder.objects.create(name="Учебный процесс", department=education),
            "edu_regulations": Folder.objects.create(
                name="Положения",
                department=education,
                parent=Folder.objects.get(name="Учебный процесс", department=education),
            ),
            "legal_contracts": Folder.objects.create(name="Договоры", department=legal),
            "legal_ocr": Folder.objects.create(
                name="OCR проект",
                department=legal,
                parent=Folder.objects.get(name="Договоры", department=legal),
            ),
            "finance_budgets": Folder.objects.create(name="Бюджеты", department=finance),
            "finance_2026": Folder.objects.create(
                name="2026",
                department=finance,
                parent=Folder.objects.get(name="Бюджеты", department=finance),
            ),
            "archive_policies": Folder.objects.create(name="Политики хранения", department=archive),
            "archive_fileplan": Folder.objects.create(name="Номенклатура дел", department=archive),
        }

        documents: dict[str, Document] = {}

        documents["mobility_2024"] = self._create_document(
            DemoDoc(
                title="Положение об академической мобильности 2024",
                file_name="academic_mobility_2024.pdf",
                file_bytes=build_simple_pdf(
                    "Academic Mobility 2024",
                    [
                        "Legacy regulation for mobility workflow.",
                        "Archived after the 2025 update.",
                    ],
                ),
                department=education,
                folder=folders["edu_regulations"],
                doc_type=doc_types["Положение"],
                description="Архивная редакция положения, использовавшаяся до запуска обновленного учебного процесса в 2025 году.",
                extracted_text=(
                    "Положение об академической мобильности 2024. "
                    "Документ определяет порядок отбора студентов, перечень форм отчетности и порядок согласования учебных результатов. "
                    "Редакция заменена новой версией 2025 года."
                ),
                doc_date=date(2024, 8, 20),
                author="Учебный офис",
                retention_category="Учебно-методический документ",
                retention_until=date(2029, 8, 20),
                status=Document.Status.ARCHIVED,
            ),
            uploaded_by=demo_admin,
        )

        documents["mobility_2025"] = self._create_document(
            DemoDoc(
                title="Положение об академической мобильности 2025",
                file_name="academic_mobility_2025.pdf",
                file_bytes=build_simple_pdf(
                    "Academic Mobility 2025",
                    [
                        "Updated regulation for academic mobility.",
                        "Includes digital archive references and KPI.",
                    ],
                ),
                department=education,
                folder=folders["edu_regulations"],
                doc_type=doc_types["Положение"],
                description="Актуальная редакция положения: цифровая маршрутная карта, единые сроки подачи документов и контроль версий приложений.",
                extracted_text=(
                    "Положение об академической мобильности 2025. "
                    "Документ утверждает новый маршрут подачи заявок, цифровой архив документов и требования к отчетности факультетов. "
                    "Отдельный раздел посвящен интеграции с электронным архивом и хранению приложений."
                ),
                doc_date=date(2025, 2, 14),
                author="Учебный офис",
                retention_category="Учебно-методический документ",
                retention_until=date(2030, 2, 14),
            ),
            uploaded_by=demo_admin,
        )
        self._add_version(
            document=documents["mobility_2025"],
            title="Положение об академической мобильности 2025",
            description="Первая редакция актуального положения без KPI по срокам рассмотрения заявок.",
            extracted_text=(
                "Положение об академической мобильности 2025. "
                "Первая редакция после обновления процедуры обмена. "
                "В документе еще не было отдельного раздела с KPI по срокам рассмотрения заявок."
            ),
            doc_date=date(2025, 1, 30),
            uploaded_by=demo_admin,
            file_name="academic_mobility_2025_v1.pdf",
            file_bytes=build_simple_pdf(
                "Academic Mobility 2025 v1",
                [
                    "First release of the updated regulation.",
                    "No KPI section yet.",
                ],
            ),
        )

        documents["mobility_appendix"] = self._create_document(
            DemoDoc(
                title="Приложение: маршрут подачи документов на академическую мобильность",
                file_name="mobility_route_sheet.pdf",
                file_bytes=build_simple_pdf(
                    "Mobility Route Sheet",
                    [
                        "Appendix with checklist for students and coordinators.",
                    ],
                ),
                department=education,
                folder=folders["edu_regulations"],
                doc_type=doc_types["Приложение"],
                description="Чек-лист по ролям: студент, факультет, международный офис, архив.",
                extracted_text=(
                    "Приложение к положению об академической мобильности. "
                    "Содержит маршрут согласования, перечень обязательных приложений, подписи ответственных сотрудников и контроль загрузки в архив."
                ),
                doc_date=date(2025, 2, 14),
                author="Учебный офис",
                retention_category="Учебно-методический документ",
                retention_until=date(2030, 2, 14),
            ),
            uploaded_by=demo_admin,
        )

        documents["ocr_contract"] = self._create_document(
            DemoDoc(
                title="Договор на внедрение OCR и AI-поиска для архива",
                file_name="ocr_ai_contract.pdf",
                file_bytes=build_simple_pdf(
                    "OCR and AI Contract",
                    [
                        "Implementation contract for OCR, semantic search, and archival metadata.",
                    ],
                ),
                department=legal,
                folder=folders["legal_ocr"],
                doc_type=doc_types["Договор"],
                description="Основной договор на внедрение OCR, извлечение метаданных и семантический поиск по электронному архиву.",
                extracted_text=(
                    "Договор на внедрение OCR и AI-поиска для архива. "
                    "Предмет договора включает OCR, семантический поиск, извлечение реквизитов и обучение сотрудников архива. "
                    "Приложением является техническое задание и поэтапный план внедрения."
                ),
                doc_date=date(2026, 1, 18),
                author="Юридический отдел",
                retention_category="Договорной документ",
                retention_until=date(2036, 1, 18),
            ),
            uploaded_by=demo_admin,
        )

        documents["ocr_appendix"] = self._create_document(
            DemoDoc(
                title="Приложение к договору: техническое задание на AI-архив",
                file_name="ocr_ai_appendix.pdf",
                file_bytes=build_simple_pdf(
                    "AI Archive Scope",
                    [
                        "Technical scope for OCR, metadata extraction, and semantic retrieval.",
                    ],
                ),
                department=legal,
                folder=folders["legal_ocr"],
                doc_type=doc_types["Приложение"],
                description="Техническое задание с требованиями к OCR, карточке документа, ролям доступа и демо-сценарию для университета.",
                extracted_text=(
                    "Приложение к договору на AI-архив. "
                    "Содержит требования к OCR, качеству карточки документа, правам доступа, версиям, постоянному идентификатору и семантическому поиску."
                ),
                doc_date=date(2026, 1, 18),
                author="Юридический отдел",
                retention_category="Договорной документ",
                retention_until=date(2036, 1, 18),
            ),
            uploaded_by=demo_admin,
        )

        documents["budget_2026"] = self._create_document(
            DemoDoc(
                title="Бюджет проекта цифрового архива на 2026 год",
                file_name="archive_budget_2026.csv",
                file_bytes=(
                    "Статья,Сумма,Комментарий\n"
                    "OCR и AI лицензии,18000000,Годовая стоимость\n"
                    "Обучение сотрудников,2500000,Семинары и методические материалы\n"
                    "Инфраструктура,6400000,Qdrant и серверные ресурсы\n"
                ).encode("utf-8"),
                department=finance,
                folder=folders["finance_2026"],
                doc_type=doc_types["Бюджет"],
                description="Бюджет внедрения электронного архива: лицензии, инфраструктура, обучение и сопровождение.",
                extracted_text=(
                    "Бюджет проекта цифрового архива на 2026 год. "
                    "Разделы бюджета: OCR и AI лицензии, обучение сотрудников, инфраструктура, сопровождение, сервисная поддержка."
                ),
                doc_date=date(2025, 12, 25),
                author="Финансовый отдел",
                retention_category="Финансовый документ",
                retention_until=date(2031, 12, 25),
            ),
            uploaded_by=demo_admin,
        )

        documents["archive_policy"] = self._create_document(
            DemoDoc(
                title="Политика хранения и выбытия электронных документов",
                file_name="retention_policy.txt",
                file_bytes=(
                    "Политика хранения электронных документов\n"
                    "Определяет сроки хранения, legal hold, роли архива и порядок контролируемого удаления.\n"
                ).encode("utf-8"),
                department=archive,
                folder=folders["archive_policies"],
                doc_type=doc_types["Политика хранения"],
                description="Правила retention schedule: сроки хранения, legal hold, контроль удаления и проверка полноты метаданных.",
                extracted_text=(
                    "Политика хранения и выбытия электронных документов. "
                    "Определяет retention schedule, legal hold, контроль удаления, журнал аудита, контроль checksum и периодические проверки качества карточек."
                ),
                doc_date=date(2026, 2, 2),
                author="Архив",
                retention_category="Политика хранения",
                retention_until=date(2036, 2, 2),
            ),
            uploaded_by=demo_admin,
        )

        documents["file_plan"] = self._create_document(
            DemoDoc(
                title="Номенклатура дел университета на 2026 год",
                file_name="file_plan_2026.pdf",
                file_bytes=build_simple_pdf(
                    "File Plan 2026",
                    [
                        "University archival file plan.",
                        "Includes departments, retention classes, and ownership.",
                    ],
                ),
                department=archive,
                folder=folders["archive_fileplan"],
                doc_type=doc_types["Номенклатура дел"],
                description="Единая архивная таксономия по подразделениям, категориям хранения и ответственным ролям.",
                extracted_text=(
                    "Номенклатура дел университета на 2026 год. "
                    "Определяет единый file plan, владельцев документов, индексы дел, сроки хранения и правила передачи в архив."
                ),
                doc_date=date(2026, 1, 10),
                author="Архив",
                retention_category="Номенклатура дел",
                retention_until=date(2031, 1, 10),
            ),
            uploaded_by=demo_admin,
        )

        documents["rector_order"] = self._create_document(
            DemoDoc(
                title="Приказ о запуске цифрового архива документов",
                file_name="launch_order.pdf",
                file_bytes=build_simple_pdf(
                    "Launch Order",
                    [
                        "Order to launch the AI-powered electronic archive.",
                        "Mentions OCR, retention, access, and training.",
                    ],
                ),
                department=rectorate,
                folder=folders["rect_orders"],
                doc_type=doc_types["Приказ"],
                description="Приказ о вводе в эксплуатацию электронного архива с OCR, AI-поиском и едиными правилами хранения.",
                extracted_text=(
                    "Приказ о запуске цифрового архива документов. "
                    "Приказ утверждает запуск платформы, регламент доступа, контроль версий, правила архивного хранения и обучение сотрудников."
                ),
                doc_date=date(2026, 3, 3),
                author="Ректорат",
                retention_category="Распорядительный документ",
                retention_until=date(2036, 3, 3),
            ),
            uploaded_by=demo_admin,
        )

        DocumentRelation.objects.create(
            from_document=documents["mobility_2025"],
            to_document=documents["mobility_2024"],
            relation_type=DocumentRelation.RelationType.REPLACES,
            confidence=0.97,
        )
        DocumentRelation.objects.create(
            from_document=documents["mobility_appendix"],
            to_document=documents["mobility_2025"],
            relation_type=DocumentRelation.RelationType.APPENDIX_TO,
            confidence=0.95,
        )
        DocumentRelation.objects.create(
            from_document=documents["ocr_appendix"],
            to_document=documents["ocr_contract"],
            relation_type=DocumentRelation.RelationType.APPENDIX_TO,
            confidence=0.96,
        )
        DocumentRelation.objects.create(
            from_document=documents["rector_order"],
            to_document=documents["ocr_contract"],
            relation_type=DocumentRelation.RelationType.MENTIONS,
            confidence=0.84,
        )
        DocumentRelation.objects.create(
            from_document=documents["file_plan"],
            to_document=documents["archive_policy"],
            relation_type=DocumentRelation.RelationType.RELATED_TO,
            confidence=0.89,
        )

        DocumentAccess.objects.create(
            document=documents["budget_2026"],
            department=archive,
            granted_by=demo_admin,
        )
        DocumentAccess.objects.create(
            document=documents["ocr_contract"],
            department=archive,
            granted_by=demo_admin,
        )

        for document in documents.values():
            DocumentActivity.objects.create(
                user=demo_admin,
                document=document,
                action=DocumentActivity.ACTION_UPLOADED,
            )

        DocumentActivity.objects.create(
            user=demo_admin,
            document=documents["mobility_2025"],
            action=DocumentActivity.ACTION_UPDATED,
        )
        DocumentActivity.objects.create(
            user=demo_admin,
            document=documents["ocr_contract"],
            action=DocumentActivity.ACTION_VIEWED,
        )
        DocumentActivity.objects.create(
            user=demo_admin,
            document=documents["budget_2026"],
            action=DocumentActivity.ACTION_DOWNLOADED,
        )

        return {
            "documents": list(documents.values()),
            "credentials": [
                ("demo_admin", demo_password),
                ("archive_demo", demo_password),
                ("legal_demo", demo_password),
                ("finance_demo", demo_password),
                ("study_demo", demo_password),
            ],
        }

    def _create_document(self, payload: DemoDoc, *, uploaded_by) -> Document:
        document = Document(
            department=payload.department,
            folder=payload.folder,
            doc_type=payload.doc_type,
            title=payload.title,
            description=payload.description,
            language=payload.language,
            document_author=payload.author,
            doc_date=payload.doc_date,
            retention_category=payload.retention_category,
            retention_until=payload.retention_until,
            legal_hold=payload.legal_hold,
            status=payload.status,
            extracted_text=payload.extracted_text,
            uploaded_by=uploaded_by,
            source_system=payload.source_system,
        )
        document.file.save(payload.file_name, ContentFile(payload.file_bytes), save=False)
        document.source_file_name = payload.file_name
        document.mime_type = detect_mime_type(payload.file_name)
        document.format_risk_level = detect_format_risk(payload.file_name)
        document.save()
        document.checksum_sha256 = calculate_sha256(document.file.path)
        document.save(update_fields=["checksum_sha256"])
        document.create_version(uploaded_by=uploaded_by)
        return document

    def _add_version(
        self,
        *,
        document: Document,
        title: str,
        description: str,
        extracted_text: str,
        doc_date: date,
        uploaded_by,
        file_name: str,
        file_bytes: bytes,
    ) -> None:
        document.title = title
        document.description = description
        document.extracted_text = extracted_text
        document.doc_date = doc_date
        document.file.save(file_name, ContentFile(file_bytes), save=False)
        document.source_file_name = file_name
        document.mime_type = detect_mime_type(file_name)
        document.format_risk_level = detect_format_risk(file_name)
        document.save()
        document.checksum_sha256 = calculate_sha256(document.file.path)
        document.save(update_fields=["title", "description", "extracted_text", "doc_date", "file", "source_file_name", "mime_type", "format_risk_level", "checksum_sha256"])
        document.create_version(uploaded_by=uploaded_by)

    def _seed_vectors(self, documents: list[Document]) -> None:
        self.stdout.write("Индексация демо-документов для семантического поиска...")
        for document in documents:
            vector = build_embedding(
                " ".join(
                    part
                    for part in [document.title, document.description, document.extracted_text]
                    if part
                )
            )
            if not vector:
                continue
            try:
                upsert_document(
                    doc_id=document.id,
                    vector=vector,
                    payload={
                        "title": document.title,
                        "department_id": document.department_id,
                        "folder_id": document.folder_id,
                        "doc_type_id": document.doc_type_id,
                        "doc_date": document.doc_date.isoformat() if document.doc_date else None,
                    },
                )
            except Exception:
                self.stdout.write(self.style.WARNING(f"Вектор для документа {document.id} не был загружен в Qdrant."))
