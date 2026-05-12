from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from dms.models import (
    AuditEvent,
    Counterparty,
    CounterpartyContact,
    Department,
    Document,
    DocumentAccess,
    DocumentActivity,
    DocumentExchange,
    DocumentRelation,
    DocumentType,
    ExchangeEvent,
    ExchangeMessage,
    ExtractedField,
    Folder,
    ImportBatch,
    ImportFile,
    Notification,
    Organization,
    OrganizationMember,
    ProcessingJob,
    Subscription,
    UsageEvent,
    WorkflowAction,
    WorkflowInstance,
    WorkflowStepTemplate,
    WorkflowTemplate,
)
from dms.services.counterparty import generate_exchange_token, hash_exchange_token
from dms.services.embedding import build_embedding
from dms.services.preservation import calculate_sha256, detect_format_risk, detect_mime_type
from dms.services.vector_store import upsert_document


User = get_user_model()

DEMO_ORG_SLUG = "demo-university"
DEMO_ORG_NAME = "Demo University Archive"
DEMO_PASSWORD = "DemoArchive2026!"


@dataclass(frozen=True)
class DemoDocumentSpec:
    key: str
    title: str
    filename: str
    file_bytes: bytes
    department: str
    folder: str
    doc_type: str
    description: str
    extracted_text: str
    doc_date: date
    author: str
    retention_category: str
    retention_until: date
    status: str = Document.Status.APPROVED
    language: str = Document.Language.RU
    legal_hold: bool = False


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_simple_pdf(title: str, lines: list[str]) -> bytes:
    text_lines = [_pdf_escape(title[:70]), *[_pdf_escape(line[:82]) for line in lines[:12]]]
    stream_lines = ["BT", "/F1 17 Tf", "50 760 Td", f"({text_lines[0]}) Tj", "/F1 10 Tf"]
    for index, line in enumerate(text_lines[1:], start=1):
        stream_lines.append(f"0 -{24 if index == 1 else 17} Td")
        stream_lines.append(f"({line}) Tj")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
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
    help = "Prepare idempotent synthetic demo data for the DMS pilot demo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-vectors",
            action="store_true",
            help="Skip optional semantic-search vector indexing.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Preparing DMS demo data..."))
        self._reset_demo_scope()
        context = self._seed_demo_data()
        if not options["skip_vectors"]:
            self._seed_vectors(context["documents"])
        self._print_summary(context)

    def _reset_demo_scope(self) -> None:
        organization = Organization.objects.filter(slug=DEMO_ORG_SLUG).first()
        if organization is None:
            return

        self.stdout.write("Resetting existing demo organization data only...")
        demo_documents = Document.objects.filter(organization=organization)
        for document in demo_documents:
            if document.file:
                document.file.delete(save=False)
            for version in document.versions.all():
                if version.file:
                    version.file.delete(save=False)

        UsageEvent.objects.filter(organization=organization).delete()
        Notification.objects.filter(organization=organization).delete()
        AuditEvent.objects.filter(organization=organization).delete()
        ExchangeMessage.objects.filter(organization=organization).delete()
        ExchangeEvent.objects.filter(organization=organization).delete()
        DocumentExchange.objects.filter(organization=organization).delete()
        CounterpartyContact.objects.filter(counterparty__organization=organization).delete()
        Counterparty.objects.filter(organization=organization).delete()
        WorkflowAction.objects.filter(organization=organization).delete()
        WorkflowInstance.objects.filter(organization=organization).delete()
        WorkflowTemplate.objects.filter(organization=organization).delete()
        ExtractedField.objects.filter(organization=organization).delete()
        ProcessingJob.objects.filter(organization=organization).delete()
        ImportFile.objects.filter(organization=organization).delete()
        ImportBatch.objects.filter(organization=organization).delete()
        DocumentRelation.objects.filter(
            from_document__organization=organization,
        ).delete()
        DocumentRelation.objects.filter(
            to_document__organization=organization,
        ).delete()
        DocumentAccess.objects.filter(document__organization=organization).delete()
        DocumentActivity.objects.filter(document__organization=organization).delete()
        demo_documents.delete()
        Folder.objects.filter(organization=organization).delete()
        DocumentType.objects.filter(organization=organization).delete()
        Department.objects.filter(organization=organization).delete()
        Subscription.objects.filter(organization=organization).delete()
        OrganizationMember.objects.filter(organization=organization).delete()
        User.objects.filter(username__in=self._demo_usernames()).delete()

        documents_dir = Path(settings.MEDIA_ROOT) / "documents"
        if documents_dir.exists():
            for child in documents_dir.iterdir():
                if child.is_dir() and child.name.startswith("demo-"):
                    shutil.rmtree(child, ignore_errors=True)

    def _seed_demo_data(self) -> dict:
        organization, _ = Organization.objects.update_or_create(
            slug=DEMO_ORG_SLUG,
            defaults={"name": DEMO_ORG_NAME, "is_active": True},
        )
        departments = self._create_departments(organization)
        users = self._create_users(organization, departments)
        doc_types = self._create_document_types(organization)
        folders = self._create_folders(organization, departments)
        documents = self._create_documents(organization, users["admin"], departments, folders, doc_types)
        self._create_document_versions(documents, users["admin"])
        self._create_related_documents(documents)
        self._create_ai_review_data(organization, documents, users)
        self._create_workflow_data(organization, documents, users)
        exchange_token = self._create_exchange_data(organization, documents, users)
        self._create_import_data(organization, departments, folders, documents, users)
        self._create_access_audit_usage(organization, departments, documents, users)
        self._create_subscription_if_possible(organization, users["admin"])
        return {
            "organization": organization,
            "departments": departments,
            "users": users,
            "documents": list(documents.values()),
            "exchange_token": exchange_token,
        }

    def _demo_usernames(self) -> list[str]:
        return [
            "demo_admin",
            "demo_legal",
            "demo_finance",
            "demo_academic",
            "demo_archive",
            "demo_approver",
        ]

    def _create_departments(self, organization: Organization) -> dict[str, Department]:
        departments = {}
        for key, name in [
            ("executive", "Executive Office"),
            ("legal", "Legal Department"),
            ("finance", "Finance Department"),
            ("academic", "Academic Office"),
            ("archive", "Central Archive"),
        ]:
            departments[key], _ = Department.objects.update_or_create(
                organization=organization,
                name=name,
                defaults={"parent": None},
            )
        return departments

    def _create_users(self, organization: Organization, departments: dict[str, Department]) -> dict[str, User]:
        specs = {
            "admin": ("demo_admin", "Demo", "Administrator", User.Role.ADMIN, None, "DMS owner", True),
            "legal": ("demo_legal", "Legal", "Reviewer", User.Role.EMPLOYEE, departments["legal"], "Legal counsel", False),
            "finance": ("demo_finance", "Finance", "Analyst", User.Role.EMPLOYEE, departments["finance"], "Finance analyst", False),
            "academic": ("demo_academic", "Academic", "Coordinator", User.Role.EMPLOYEE, departments["academic"], "Academic coordinator", False),
            "archive": ("demo_archive", "Archive", "Manager", User.Role.EMPLOYEE, departments["archive"], "Archive manager", False),
            "approver": ("demo_approver", "Pilot", "Approver", User.Role.EMPLOYEE, departments["executive"], "Executive approver", False),
        }
        users = {}
        for key, (username, first_name, last_name, role, department, position, is_staff) in specs.items():
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@example.test",
                    "role": role,
                    "department": department,
                    "position": position,
                    "is_staff": is_staff,
                    "is_active": True,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            OrganizationMember.objects.update_or_create(
                organization=organization,
                user=user,
                defaults={
                    "role": (
                        OrganizationMember.Role.ADMIN
                        if role == User.Role.ADMIN
                        else OrganizationMember.Role.MEMBER
                    ),
                    "is_active": True,
                },
            )
            users[key] = user
        return users

    def _create_document_types(self, organization: Organization) -> dict[str, DocumentType]:
        doc_types = {}
        for key, name in [
            ("order", "Order"),
            ("policy", "Policy"),
            ("contract", "Contract"),
            ("appendix", "Appendix"),
            ("invoice", "Invoice"),
            ("act", "Completion Act"),
            ("budget", "Budget"),
            ("file_plan", "File Plan"),
        ]:
            doc_types[key], _ = DocumentType.objects.update_or_create(
                organization=organization,
                name=name,
                defaults={},
            )
        return doc_types

    def _create_folders(
        self,
        organization: Organization,
        departments: dict[str, Department],
    ) -> dict[str, Folder]:
        folders = {}
        specs = [
            ("orders", "Executive Orders", departments["executive"], None),
            ("contracts", "Contracts", departments["legal"], None),
            ("ocr_project", "OCR Pilot", departments["legal"], "contracts"),
            ("budgets", "Budgets", departments["finance"], None),
            ("budget_2026", "2026", departments["finance"], "budgets"),
            ("academic_rules", "Academic Regulations", departments["academic"], None),
            ("mobility", "Academic Mobility", departments["academic"], "academic_rules"),
            ("retention", "Retention Policies", departments["archive"], None),
            ("file_plan", "File Plan", departments["archive"], None),
        ]
        for key, name, department, parent_key in specs:
            folders[key], _ = Folder.objects.update_or_create(
                organization=organization,
                department=department,
                parent=folders.get(parent_key),
                name=name,
                defaults={},
            )
        return folders

    def _document_specs(self) -> list[DemoDocumentSpec]:
        return [
            DemoDocumentSpec(
                key="launch_order",
                title="Order on Launching the Digital Document Archive",
                filename="demo_launch_order.pdf",
                file_bytes=build_simple_pdf(
                    "Digital Archive Launch Order",
                    [
                        "Synthetic demo order approving the DMS pilot.",
                        "Covers upload, AI review, workflow, audit, and evidence export.",
                    ],
                ),
                department="executive",
                folder="orders",
                doc_type="order",
                description="Pilot order that starts the internal DMS rollout and assigns ownership.",
                extracted_text="Order on launching the digital archive. The order approves the pilot scope, responsible departments, access rules, workflow, evidence package, audit trail, and reporting dashboards.",
                doc_date=date(2026, 3, 3),
                author="Executive Office",
                retention_category="Executive order",
                retention_until=date(2036, 3, 3),
            ),
            DemoDocumentSpec(
                key="mobility_regulation",
                title="Academic Mobility Regulation 2025",
                filename="demo_mobility_regulation.pdf",
                file_bytes=build_simple_pdf(
                    "Academic Mobility Regulation 2025",
                    [
                        "Synthetic regulation for academic exchange documents.",
                        "Includes document checklist and archive responsibilities.",
                    ],
                ),
                department="academic",
                folder="mobility",
                doc_type="policy",
                description="Current academic mobility regulation used to demonstrate related documents and AI metadata review.",
                extracted_text="Academic mobility regulation 2025. This synthetic document describes application deadlines, faculty approvals, archive submission, and document checklist responsibilities.",
                doc_date=date(2025, 2, 14),
                author="Academic Office",
                retention_category="Academic regulation",
                retention_until=date(2030, 2, 14),
            ),
            DemoDocumentSpec(
                key="mobility_appendix",
                title="Appendix A: Academic Mobility Document Checklist",
                filename="demo_mobility_appendix.pdf",
                file_bytes=build_simple_pdf(
                    "Academic Mobility Checklist",
                    [
                        "Synthetic appendix connected to the mobility regulation.",
                    ],
                ),
                department="academic",
                folder="mobility",
                doc_type="appendix",
                description="Checklist appendix for academic mobility packages.",
                extracted_text="Appendix A to the academic mobility regulation. The checklist lists application, agreement, transcript, insurance confirmation, and archive upload confirmation.",
                doc_date=date(2025, 2, 14),
                author="Academic Office",
                retention_category="Academic appendix",
                retention_until=date(2030, 2, 14),
            ),
            DemoDocumentSpec(
                key="ocr_contract",
                title="Contract for OCR and AI Search Pilot",
                filename="demo_ocr_contract.pdf",
                file_bytes=build_simple_pdf(
                    "OCR and AI Search Pilot Contract",
                    [
                        "Synthetic supplier contract for OCR and semantic search.",
                        "Used for exchange, workflow, and evidence demo.",
                    ],
                ),
                department="legal",
                folder="ocr_project",
                doc_type="contract",
                description="Synthetic contract for the DMS pilot supplier engagement.",
                extracted_text="Contract for OCR and AI search pilot. The supplier provides OCR, metadata extraction, semantic search, pilot support, and training materials for the archive team.",
                doc_date=date(2026, 1, 18),
                author="Legal Department",
                retention_category="Contract",
                retention_until=date(2036, 1, 18),
                status=Document.Status.IN_REVIEW,
            ),
            DemoDocumentSpec(
                key="ocr_spec",
                title="Technical Specification for OCR and AI Archive",
                filename="demo_ocr_spec.pdf",
                file_bytes=build_simple_pdf(
                    "OCR and AI Archive Specification",
                    [
                        "Synthetic technical appendix for the OCR pilot.",
                    ],
                ),
                department="legal",
                folder="ocr_project",
                doc_type="appendix",
                description="Technical appendix connected to the OCR pilot contract.",
                extracted_text="Technical specification for OCR and AI archive. It defines metadata fields, manual validation, protected file access, semantic search, and evidence export requirements.",
                doc_date=date(2026, 1, 18),
                author="Legal Department",
                retention_category="Contract appendix",
                retention_until=date(2036, 1, 18),
            ),
            DemoDocumentSpec(
                key="pilot_invoice",
                title="Invoice for DMS Pilot Services",
                filename="demo_pilot_invoice.csv",
                file_bytes=b"Line,Amount,Currency\nOCR setup,1200000,KZT\nPilot support,800000,KZT\nTraining,350000,KZT\n",
                department="finance",
                folder="budget_2026",
                doc_type="invoice",
                description="Synthetic invoice for the DMS pilot service package.",
                extracted_text="Invoice for DMS pilot services. Lines include OCR setup, pilot support, and archive team training.",
                doc_date=date(2026, 2, 10),
                author="Finance Department",
                retention_category="Finance document",
                retention_until=date(2031, 2, 10),
                language=Document.Language.EN,
            ),
            DemoDocumentSpec(
                key="pilot_act",
                title="Completion Act for DMS Pilot Milestone 1",
                filename="demo_pilot_completion_act.pdf",
                file_bytes=build_simple_pdf(
                    "Completion Act",
                    [
                        "Synthetic act confirming milestone one acceptance.",
                    ],
                ),
                department="finance",
                folder="budget_2026",
                doc_type="act",
                description="Synthetic completion act tied to the pilot contract and invoice.",
                extracted_text="Completion act for DMS pilot milestone one. Confirms delivery of initial upload, AI review, workflow, and external exchange demonstration.",
                doc_date=date(2026, 2, 20),
                author="Finance Department",
                retention_category="Finance document",
                retention_until=date(2031, 2, 20),
            ),
            DemoDocumentSpec(
                key="retention_policy",
                title="Electronic Document Retention Policy",
                filename="demo_retention_policy.txt",
                file_bytes=b"Electronic Document Retention Policy\nSynthetic demo policy for retention, legal hold, audit trail, and deletion review.\n",
                department="archive",
                folder="retention",
                doc_type="policy",
                description="Policy used to explain retention metadata, evidence export, and archive governance.",
                extracted_text="Electronic document retention policy. The policy defines retention categories, legal hold, audit trail expectations, checksum control, and controlled deletion review.",
                doc_date=date(2026, 2, 2),
                author="Central Archive",
                retention_category="Retention policy",
                retention_until=date(2036, 2, 2),
            ),
            DemoDocumentSpec(
                key="file_plan",
                title="University File Plan 2026",
                filename="demo_file_plan.pdf",
                file_bytes=build_simple_pdf(
                    "University File Plan 2026",
                    [
                        "Synthetic file plan with departments and retention classes.",
                    ],
                ),
                department="archive",
                folder="file_plan",
                doc_type="file_plan",
                description="File plan that maps departments, folders, and retention classes.",
                extracted_text="University file plan 2026. It defines document categories, department owners, archive transfer rules, retention periods, and folder hierarchy.",
                doc_date=date(2026, 1, 10),
                author="Central Archive",
                retention_category="File plan",
                retention_until=date(2031, 1, 10),
            ),
        ]

    def _create_documents(
        self,
        organization: Organization,
        uploaded_by: User,
        departments: dict[str, Department],
        folders: dict[str, Folder],
        doc_types: dict[str, DocumentType],
    ) -> dict[str, Document]:
        documents = {}
        for spec in self._document_specs():
            document = Document(
                organization=organization,
                department=departments[spec.department],
                folder=folders[spec.folder],
                doc_type=doc_types[spec.doc_type],
                title=spec.title,
                description=spec.description,
                language=spec.language,
                document_author=spec.author,
                doc_date=spec.doc_date,
                retention_category=spec.retention_category,
                retention_until=spec.retention_until,
                legal_hold=spec.legal_hold,
                status=spec.status,
                extracted_text=spec.extracted_text,
                uploaded_by=uploaded_by,
                source_system="demo_seed",
                source_file_name=spec.filename,
                mime_type=detect_mime_type(spec.filename),
                format_risk_level=detect_format_risk(spec.filename),
            )
            document.file.save(spec.filename, ContentFile(spec.file_bytes), save=False)
            document.save()
            document.checksum_sha256 = calculate_sha256(document.file.path)
            document.save(update_fields=["checksum_sha256"])
            document.create_version(uploaded_by=uploaded_by)
            documents[spec.key] = document
        return documents

    def _create_document_versions(self, documents: dict[str, Document], uploaded_by: User) -> None:
        document = documents["mobility_regulation"]
        document.description = "Updated regulation after adding pilot archive responsibilities."
        document.extracted_text += " Version two adds pilot archive responsibilities and manual AI review."
        document.file.save(
            "demo_mobility_regulation_v2.pdf",
            ContentFile(build_simple_pdf("Academic Mobility Regulation v2", ["Adds archive responsibilities and manual AI review."])),
            save=False,
        )
        document.source_file_name = "demo_mobility_regulation_v2.pdf"
        document.mime_type = detect_mime_type(document.source_file_name)
        document.format_risk_level = detect_format_risk(document.source_file_name)
        document.save()
        document.checksum_sha256 = calculate_sha256(document.file.path)
        document.save(update_fields=["description", "extracted_text", "file", "source_file_name", "mime_type", "format_risk_level", "checksum_sha256"])
        document.create_version(uploaded_by=uploaded_by)

    def _create_related_documents(self, documents: dict[str, Document]) -> None:
        relations = [
            ("mobility_appendix", "mobility_regulation", DocumentRelation.RelationType.APPENDIX_TO, "0.95"),
            ("ocr_spec", "ocr_contract", DocumentRelation.RelationType.APPENDIX_TO, "0.96"),
            ("pilot_invoice", "ocr_contract", DocumentRelation.RelationType.INVOICE, "0.91"),
            ("pilot_act", "ocr_contract", DocumentRelation.RelationType.ACT, "0.91"),
            ("launch_order", "ocr_contract", DocumentRelation.RelationType.MENTIONS, "0.84"),
            ("file_plan", "retention_policy", DocumentRelation.RelationType.RELATED_TO, "0.89"),
        ]
        for from_key, to_key, relation_type, confidence in relations:
            DocumentRelation.objects.create(
                from_document=documents[from_key],
                to_document=documents[to_key],
                relation_type=relation_type,
                confidence=confidence,
            )

    def _create_ai_review_data(
        self,
        organization: Organization,
        documents: dict[str, Document],
        users: dict[str, User],
    ) -> None:
        job = ProcessingJob.objects.create(
            organization=organization,
            document=documents["ocr_contract"],
            created_by=users["legal"],
            status=ProcessingJob.Status.REVIEWED,
            source=ProcessingJob.Source.UPLOAD,
            extracted_text_length=len(documents["ocr_contract"].extracted_text),
            raw_result={
                "title_ru": "Contract for OCR and AI Search Pilot",
                "summary_ru": "Synthetic supplier contract for OCR, metadata extraction, and semantic search.",
                "language": "EN",
            },
            started_at=timezone.now() - timedelta(days=3),
            completed_at=timezone.now() - timedelta(days=3, minutes=-4),
        )
        field_specs = [
            ("title", "Title", "Contract for OCR and AI Search Pilot", ExtractedField.Status.CONFIRMED, "0.94"),
            ("description", "Description", "Synthetic supplier contract for OCR and semantic search pilot.", ExtractedField.Status.SUGGESTED, "0.88"),
            ("language", "Language", Document.Language.EN, ExtractedField.Status.REJECTED, "0.73"),
            ("document_author", "Document author", "Legal Department", ExtractedField.Status.CONFIRMED, "0.91"),
        ]
        for field_name, label, value, status, confidence in field_specs:
            ExtractedField.objects.create(
                organization=organization,
                job=job,
                document=documents["ocr_contract"],
                field_name=field_name,
                label=label,
                value=value,
                confidence=confidence,
                status=status,
                reviewed_by=users["legal"] if status != ExtractedField.Status.SUGGESTED else None,
                reviewed_at=timezone.now() - timedelta(days=2) if status != ExtractedField.Status.SUGGESTED else None,
            )

    def _create_workflow_data(
        self,
        organization: Organization,
        documents: dict[str, Document],
        users: dict[str, User],
    ) -> None:
        template = WorkflowTemplate.objects.create(
            organization=organization,
            name="Pilot Document Approval",
            description="Synthetic two-step approval template for demo.",
            created_by=users["admin"],
        )
        legal_step = WorkflowStepTemplate.objects.create(
            template=template,
            order=1,
            name="Legal review",
            approver_department=users["legal"].department,
            instructions="Check legal terms and related appendices.",
        )
        executive_step = WorkflowStepTemplate.objects.create(
            template=template,
            order=2,
            name="Executive approval",
            approver_user=users["approver"],
            instructions="Confirm pilot readiness.",
        )
        active = WorkflowInstance.objects.create(
            organization=organization,
            document=documents["ocr_contract"],
            template=template,
            current_step_template=legal_step,
            started_by=users["legal"],
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowAction.objects.create(
            organization=organization,
            instance=active,
            document=documents["ocr_contract"],
            step_template=legal_step,
            actor=users["legal"],
            action_type=WorkflowAction.ActionType.START,
            comment="Started legal review for the OCR pilot contract.",
        )
        approved = WorkflowInstance.objects.create(
            organization=organization,
            document=documents["launch_order"],
            template=template,
            current_step_template=None,
            started_by=users["admin"],
            status=WorkflowInstance.Status.APPROVED,
            completed_at=timezone.now() - timedelta(days=1),
        )
        for step, actor, action, comment in [
            (legal_step, users["legal"], WorkflowAction.ActionType.START, "Started launch order approval."),
            (legal_step, users["legal"], WorkflowAction.ActionType.APPROVE, "Legal review completed."),
            (executive_step, users["approver"], WorkflowAction.ActionType.APPROVE, "Approved for pilot demo."),
        ]:
            WorkflowAction.objects.create(
                organization=organization,
                instance=approved,
                document=documents["launch_order"],
                step_template=step,
                actor=actor,
                action_type=action,
                comment=comment,
            )

    def _create_exchange_data(
        self,
        organization: Organization,
        documents: dict[str, Document],
        users: dict[str, User],
    ) -> str:
        counterparty = Counterparty.objects.create(
            organization=organization,
            name="Northwind Digital LLP",
            email="contracts@example.test",
            contact_name="Demo Contract Desk",
            created_by=users["legal"],
        )
        contact = CounterpartyContact.objects.create(
            counterparty=counterparty,
            name="Demo Contract Reviewer",
            email="reviewer@example.test",
            position="Partner manager",
            phone="+7 700 000 0000",
            created_by=users["legal"],
        )
        token = generate_exchange_token()
        outgoing = DocumentExchange.objects.create(
            organization=organization,
            document=documents["ocr_contract"],
            counterparty=counterparty,
            counterparty_contact=contact,
            sent_by=users["legal"],
            direction=DocumentExchange.Direction.OUTGOING,
            business_document_type=DocumentExchange.BusinessDocumentType.CONTRACT,
            status=DocumentExchange.Status.ACCEPTED,
            token_hash=hash_exchange_token(token),
            token_hint=token[-6:],
            message="Please review the synthetic OCR pilot contract.",
            expires_at=timezone.now() + timedelta(days=14),
            opened_at=timezone.now() - timedelta(days=1, hours=3),
            responded_at=timezone.now() - timedelta(days=1),
        )
        for event_type, comment in [
            (ExchangeEvent.EventType.SENT, "Sent to synthetic counterparty."),
            (ExchangeEvent.EventType.OPENED, "External reviewer opened the portal."),
            (ExchangeEvent.EventType.DOWNLOADED, "External reviewer downloaded the file."),
            (ExchangeEvent.EventType.COMMENTED, "External reviewer left a comment."),
            (ExchangeEvent.EventType.ACCEPTED, "External reviewer accepted the document."),
        ]:
            ExchangeEvent.objects.create(
                organization=organization,
                exchange=outgoing,
                document=outgoing.document,
                event_type=event_type,
                actor_name="Demo Contract Reviewer",
                actor_email="reviewer@example.test",
                comment=comment,
            )
        ExchangeMessage.objects.create(
            organization=organization,
            exchange=outgoing,
            document=outgoing.document,
            counterparty=counterparty,
            counterparty_contact=contact,
            user=users["legal"],
            author_type=ExchangeMessage.AuthorType.INTERNAL,
            body="This is a synthetic pilot contract prepared for demonstration.",
            source_event_type=ExchangeEvent.EventType.SENT,
        )
        ExchangeMessage.objects.create(
            organization=organization,
            exchange=outgoing,
            document=outgoing.document,
            counterparty=counterparty,
            counterparty_contact=contact,
            author_type=ExchangeMessage.AuthorType.EXTERNAL,
            body="The demo counterparty has reviewed and accepted the document.",
            source_event_type=ExchangeEvent.EventType.ACCEPTED,
        )

        incoming_token = generate_exchange_token()
        DocumentExchange.objects.create(
            organization=organization,
            document=documents["pilot_invoice"],
            counterparty=counterparty,
            counterparty_contact=contact,
            received_by=users["finance"],
            direction=DocumentExchange.Direction.INCOMING,
            business_document_type=DocumentExchange.BusinessDocumentType.INVOICE,
            status=DocumentExchange.Status.RECEIVED,
            token_hash=hash_exchange_token(incoming_token),
            token_hint=incoming_token[-6:],
            message="Synthetic incoming invoice for the pilot.",
            received_at=timezone.now() - timedelta(days=2),
        )
        return token

    def _create_import_data(
        self,
        organization: Organization,
        departments: dict[str, Department],
        folders: dict[str, Folder],
        documents: dict[str, Document],
        users: dict[str, User],
    ) -> None:
        batch = ImportBatch.objects.create(
            organization=organization,
            department=departments["archive"],
            folder=folders["retention"],
            created_by=users["archive"],
            status=ImportBatch.Status.COMPLETED_WITH_ERRORS,
            source="demo_seed",
            total_files=3,
            imported_files=2,
            duplicate_files=1,
            failed_files=0,
            completed_at=timezone.now() - timedelta(days=1),
        )
        for document in [documents["retention_policy"], documents["file_plan"]]:
            ImportFile.objects.create(
                batch=batch,
                organization=organization,
                document=document,
                original_file_name=document.source_file_name,
                checksum_sha256=document.checksum_sha256,
                status=ImportFile.Status.IMPORTED,
            )
        ImportFile.objects.create(
            batch=batch,
            organization=organization,
            duplicate_of=documents["retention_policy"],
            original_file_name="demo_retention_policy_duplicate.txt",
            checksum_sha256=documents["retention_policy"].checksum_sha256,
            status=ImportFile.Status.DUPLICATE,
        )

    def _create_access_audit_usage(
        self,
        organization: Organization,
        departments: dict[str, Department],
        documents: dict[str, Document],
        users: dict[str, User],
    ) -> None:
        DocumentAccess.objects.create(
            document=documents["ocr_contract"],
            department=departments["archive"],
            granted_by=users["legal"],
        )
        DocumentAccess.objects.create(
            document=documents["pilot_invoice"],
            department=departments["archive"],
            granted_by=users["finance"],
        )
        for document in documents.values():
            DocumentActivity.objects.create(
                user=users["admin"],
                document=document,
                action=DocumentActivity.ACTION_UPLOADED,
            )
            AuditEvent.objects.create(
                organization=organization,
                user=users["admin"],
                document=document,
                event_type=AuditEvent.EventType.DOCUMENT_UPLOADED,
                metadata={
                    "source": "demo_seed",
                    "demo": True,
                },
            )
            UsageEvent.objects.create(
                organization=organization,
                user=users["admin"],
                document=document,
                event_type=UsageEvent.EventType.DOCUMENT_UPLOADED,
                source="demo_seed",
                metadata={"demo": True},
            )
        for event_type, document in [
            (UsageEvent.EventType.AI_PROCESSING_COMPLETED, documents["ocr_contract"]),
            (UsageEvent.EventType.WORKFLOW_ACTION, documents["launch_order"]),
            (UsageEvent.EventType.EXCHANGE_EVENT, documents["ocr_contract"]),
            (UsageEvent.EventType.EVIDENCE_EXPORTED, documents["ocr_contract"]),
            (UsageEvent.EventType.DOCUMENT_RELATION_CREATED, documents["mobility_regulation"]),
        ]:
            UsageEvent.objects.create(
                organization=organization,
                user=users["admin"],
                document=document,
                event_type=event_type,
                source="demo_seed",
                quantity=2 if event_type == UsageEvent.EventType.WORKFLOW_ACTION else 1,
                metadata={"demo": True},
            )
        AuditEvent.objects.create(
            organization=organization,
            user=users["legal"],
            document=documents["ocr_contract"],
            event_type=AuditEvent.EventType.EXCHANGE_ACCEPTED,
            metadata={"demo": True, "counterparty": "Northwind Digital LLP"},
        )

    def _create_subscription_if_possible(self, organization: Organization, user: User) -> None:
        from dms.models import Plan

        plan = Plan.objects.filter(is_active=True).order_by("price_amount", "name").first()
        if plan is None:
            return
        Subscription.objects.update_or_create(
            organization=organization,
            defaults={
                "plan": plan,
                "status": Subscription.Status.TRIALING,
                "current_period_start": date.today(),
                "current_period_end": date.today() + timedelta(days=30),
                "is_default": True,
                "created_by": user,
            },
        )

    def _seed_vectors(self, documents: list[Document]) -> None:
        self.stdout.write("Indexing demo documents for semantic search...")
        for document in documents:
            text = " ".join(
                part for part in [document.title, document.description, document.extracted_text] if part
            )
            vector = build_embedding(text)
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
                self.stdout.write(self.style.WARNING(f"Vector indexing skipped for document {document.id}."))

    def _print_summary(self, context: dict) -> None:
        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        self.stdout.write(f"Organization: {context['organization'].name} ({DEMO_ORG_SLUG})")
        self.stdout.write("Demo credentials:")
        for username in self._demo_usernames():
            self.stdout.write(f"  - {username} / {DEMO_PASSWORD}")
        self.stdout.write("Suggested demo route:")
        self.stdout.write("  1. Login as demo_admin.")
        self.stdout.write("  2. Open Documents and inspect 'Contract for OCR and AI Search Pilot'.")
        self.stdout.write("  3. Review AI suggestions, related documents, workflow, exchange history, evidence export, usage, and analytics.")
        self.stdout.write(f"External portal demo URL path: /portal/exchanges/{context['exchange_token']}/")
