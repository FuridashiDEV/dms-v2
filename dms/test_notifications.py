import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dms.models import CounterpartyContact, Department, Notification, User, WorkflowStepTemplate, WorkflowTemplate
from dms.services.ai_processing import run_document_ai_processing
from dms.services.counterparty import create_document_exchange
from dms.services.workflow import start_workflow
from dms.test_factories import make_counterparty, make_document, make_org_context


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="uni_dms_notifications_media_")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class NotificationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.context = make_org_context(slug="notifications", username="notifications-owner")
        self.approver_department = Department.objects.create(
            organization=self.context.organization,
            name="Approver Department",
        )
        self.approver = User.objects.create_user(
            username="notifications-approver",
            password="password123",
            department=self.approver_department,
        )
        self.other_context = make_org_context(slug="notifications-other", username="notifications-outsider")
        self.document = make_document(context=self.context, title="Notification document")
        self.counterparty = make_counterparty(context=self.context, name="Notify LLP", email="notify@example.test")

    def test_workflow_assignment_creates_notification(self):
        template = WorkflowTemplate.objects.create(
            organization=self.context.organization,
            name="Notification approval",
            created_by=self.context.user,
        )
        WorkflowStepTemplate.objects.create(
            template=template,
            order=1,
            name="Approver step",
            approver_user=self.approver,
        )

        start_workflow(document=self.document, template=template, user=self.context.user)

        notification = Notification.objects.get(
            recipient=self.approver,
            notification_type=Notification.Type.WORKFLOW_ASSIGNED,
        )
        self.assertEqual(notification.organization, self.context.organization)
        self.assertEqual(notification.related_document, self.document)
        self.assertNotIn("portal/exchanges", notification.message)

    @patch("dms.services.counterparty.generate_exchange_token", return_value="stage24-secure-token")
    def test_external_comment_creates_notification_without_secure_token(self, _token_mock):
        contact = CounterpartyContact.objects.create(
            counterparty=self.counterparty,
            name="Notify Contact",
            email="contact@example.test",
            created_by=self.context.user,
        )
        created = create_document_exchange(
            document=self.document,
            counterparty=self.counterparty,
            counterparty_contact=contact,
            user=self.context.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

        response = self.client.post(
            reverse("dms:counterparty_portal_action", args=[created.token, "comment"]),
            {"comment": "Please check /portal/exchanges/stage24-secure-token/"},
        )

        self.assertRedirects(response, reverse("dms:counterparty_portal", args=[created.token]))
        notification = Notification.objects.get(
            recipient=self.context.user,
            notification_type=Notification.Type.EXCHANGE_COMMENTED,
        )
        self.assertEqual(notification.related_exchange, created.exchange)
        self.assertIn("[redacted]", notification.message)
        self.assertNotIn("stage24-secure-token", notification.title)
        self.assertNotIn("stage24-secure-token", notification.message)

    def test_user_sees_only_own_notifications_and_current_organization(self):
        own = Notification.objects.create(
            organization=self.context.organization,
            recipient=self.context.user,
            notification_type=Notification.Type.AI_REVIEW_READY,
            title="Own notification",
            message="Visible",
            related_document=self.document,
        )
        Notification.objects.create(
            organization=self.context.organization,
            recipient=self.approver,
            notification_type=Notification.Type.AI_REVIEW_READY,
            title="Other user notification",
            message="Hidden",
        )
        Notification.objects.create(
            organization=self.other_context.organization,
            recipient=self.context.user,
            notification_type=Notification.Type.AI_REVIEW_READY,
            title="Other organization notification",
            message="Hidden",
        )
        self.client.force_login(self.context.user)

        response = self.client.get(reverse("dms:notification_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own.title)
        self.assertContains(response, "Notifications (1)")
        self.assertNotContains(response, "Other user notification")
        self.assertNotContains(response, "Other organization notification")

    def test_notification_can_be_marked_read(self):
        notification = Notification.objects.create(
            organization=self.context.organization,
            recipient=self.context.user,
            notification_type=Notification.Type.AI_REVIEW_READY,
            title="Read me",
            message="Needs action",
        )
        self.client.force_login(self.context.user)

        response = self.client.post(reverse("dms:notification_mark_read", args=[notification.id]))

        self.assertRedirects(response, reverse("dms:notification_list"))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

    def test_ai_review_ready_creates_notification(self):
        run_document_ai_processing(
            document=self.document,
            text="Invoice dated 2026-05-13 with contract metadata.",
            user=self.context.user,
            parser=lambda **kwargs: {
                "title_ru": "AI suggested title",
                "summary_ru": "AI suggested summary",
            },
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.context.user,
                notification_type=Notification.Type.AI_REVIEW_READY,
                related_document=self.document,
            ).exists()
        )
