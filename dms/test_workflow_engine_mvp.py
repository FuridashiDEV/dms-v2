import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from dms.models import (
    AuditEvent,
    Department,
    Document,
    WorkflowAction,
    WorkflowInstance,
    WorkflowStepTemplate,
    WorkflowTemplate,
    User,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_workflow_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class WorkflowEngineMvpTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.department = Department.objects.create(name="Workflow department")
        self.other_department = Department.objects.create(name="Workflow other")
        self.owner = User.objects.create_user(
            username="workflow-owner",
            password="password123",
            department=self.department,
        )
        self.approver = User.objects.create_user(
            username="workflow-approver",
            password="password123",
            department=self.department,
        )
        self.outsider = User.objects.create_user(
            username="workflow-outsider",
            password="password123",
            department=self.other_department,
        )
        self.admin = User.objects.create_user(
            username="workflow-admin",
            password="password123",
            role=User.Role.ADMIN,
        )
        self.document = Document.objects.create(
            department=self.department,
            title="Workflow contract",
            file=SimpleUploadedFile("workflow.txt", b"workflow payload"),
            uploaded_by=self.owner,
        )
        self.document.create_version(uploaded_by=self.owner)
        self.template = WorkflowTemplate.objects.create(
            organization=self.department.organization,
            name="Basic approval",
            created_by=self.admin,
        )
        self.step = WorkflowStepTemplate.objects.create(
            template=self.template,
            order=1,
            name="Department approval",
            approver_department=self.department,
        )

    def test_start_workflow_changes_document_status_and_records_audit(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("dms:document_workflow_start", args=[self.document.id]),
            {
                "template": str(self.template.id),
                "comment": "Please review",
            },
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.IN_REVIEW)
        instance = WorkflowInstance.objects.get(document=self.document)
        self.assertEqual(instance.status, WorkflowInstance.Status.ACTIVE)
        self.assertEqual(instance.current_step_template, self.step)
        self.assertEqual(self.document.versions.count(), 2)
        self.assertTrue(
            WorkflowAction.objects.filter(
                instance=instance,
                action_type=WorkflowAction.ActionType.START,
                comment="Please review",
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.WORKFLOW_STARTED,
                metadata__workflow_instance_id=instance.id,
            ).exists()
        )

    def test_assigned_department_approver_can_approve_final_step(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("dms:document_workflow_start", args=[self.document.id]),
            {"template": str(self.template.id)},
        )
        instance = WorkflowInstance.objects.get(document=self.document)
        self.client.force_login(self.approver)

        response = self.client.post(
            reverse(
                "dms:document_workflow_action",
                args=[self.document.id, instance.id, "approve"],
            ),
            {"comment": "Approved"},
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        self.document.refresh_from_db()
        instance.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.APPROVED)
        self.assertEqual(instance.status, WorkflowInstance.Status.APPROVED)
        self.assertIsNone(instance.current_step_template)
        self.assertEqual(self.document.versions.count(), 3)
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.WORKFLOW_COMPLETED,
                metadata__decision="approved",
            ).exists()
        )

    def test_outsider_cannot_approve_workflow(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("dms:document_workflow_start", args=[self.document.id]),
            {"template": str(self.template.id)},
        )
        instance = WorkflowInstance.objects.get(document=self.document)
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse(
                "dms:document_workflow_action",
                args=[self.document.id, instance.id, "approve"],
            )
        )

        self.assertEqual(response.status_code, 404)
        self.document.refresh_from_db()
        instance.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.IN_REVIEW)
        self.assertEqual(instance.status, WorkflowInstance.Status.ACTIVE)

    def test_request_changes_closes_workflow_and_updates_document_status(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("dms:document_workflow_start", args=[self.document.id]),
            {"template": str(self.template.id)},
        )
        instance = WorkflowInstance.objects.get(document=self.document)
        self.client.force_login(self.approver)

        response = self.client.post(
            reverse(
                "dms:document_workflow_action",
                args=[self.document.id, instance.id, "request-changes"],
            ),
            {"comment": "Please fix metadata"},
        )

        self.assertRedirects(response, reverse("dms:document_detail", args=[self.document.id]))
        self.document.refresh_from_db()
        instance.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.CHANGES_REQUESTED)
        self.assertEqual(instance.status, WorkflowInstance.Status.CHANGES_REQUESTED)
        self.assertTrue(
            WorkflowAction.objects.filter(
                instance=instance,
                action_type=WorkflowAction.ActionType.REQUEST_CHANGES,
                comment="Please fix metadata",
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                document=self.document,
                event_type=AuditEvent.EventType.WORKFLOW_CHANGES_REQUESTED,
            ).exists()
        )
