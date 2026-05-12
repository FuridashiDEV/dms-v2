from __future__ import annotations

import re

from django.contrib.auth import get_user_model

from dms.models import Document, DocumentExchange, ExtractedField, Notification, OrganizationMember, ProcessingJob, WorkflowInstance
from dms.utils import get_user_organizations


TOKEN_PATTERNS = (
    re.compile(r"/portal/exchanges/[^/\s]+/?", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_-]{24,}\b"),
)


def sanitize_notification_text(value: str) -> str:
    text = (value or "").strip()
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:2000]


def _recipient_in_organization(*, recipient, organization) -> bool:
    if not recipient or not getattr(recipient, "is_active", False):
        return False
    if getattr(recipient, "department_id", None) and recipient.department.organization_id == organization.id:
        return True
    return OrganizationMember.objects.filter(
        organization=organization,
        user=recipient,
        is_active=True,
    ).exists()


def create_notification(
    *,
    organization,
    recipient,
    notification_type: str,
    title: str,
    message: str = "",
    actor=None,
    related_document: Document | None = None,
    related_exchange: DocumentExchange | None = None,
) -> Notification | None:
    if not _recipient_in_organization(recipient=recipient, organization=organization):
        return None
    if related_document is not None and related_document.organization_id != organization.id:
        return None
    if related_exchange is not None and related_exchange.organization_id != organization.id:
        return None
    return Notification.objects.create(
        organization=organization,
        recipient=recipient,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        notification_type=notification_type,
        title=sanitize_notification_text(title)[:255],
        message=sanitize_notification_text(message),
        related_document=related_document,
        related_exchange=related_exchange,
    )


def _department_recipients(department):
    User = get_user_model()
    return User.objects.filter(
        is_active=True,
        department=department,
    )


def notify_workflow_assignment(*, instance: WorkflowInstance, actor=None) -> list[Notification]:
    step = instance.current_step_template
    if step is None:
        return []

    recipients = []
    if step.approver_user_id:
        recipients.append(step.approver_user)
    elif step.approver_department_id:
        recipients.extend(_department_recipients(step.approver_department))

    notifications = []
    for recipient in {user.id: user for user in recipients if user}.values():
        notification = create_notification(
            organization=instance.organization,
            recipient=recipient,
            actor=actor,
            notification_type=Notification.Type.WORKFLOW_ASSIGNED,
            title="Workflow approval assigned",
            message=f"Document '{instance.document.title}' is waiting for approval step '{step.name}'.",
            related_document=instance.document,
        )
        if notification is not None:
            notifications.append(notification)
    return notifications


def notify_ai_review_ready(*, job: ProcessingJob, actor=None) -> list[Notification]:
    if not job.fields.filter(status=ExtractedField.Status.SUGGESTED).exists():
        return []

    recipients = []
    if job.created_by_id:
        recipients.append(job.created_by)
    if job.document.uploaded_by_id:
        recipients.append(job.document.uploaded_by)
    if not recipients:
        recipients.extend(_department_recipients(job.document.department))

    notifications = []
    for recipient in {user.id: user for user in recipients if user}.values():
        notification = create_notification(
            organization=job.organization,
            recipient=recipient,
            actor=actor,
            notification_type=Notification.Type.AI_REVIEW_READY,
            title="AI fields need review",
            message=f"Document '{job.document.title}' has AI extraction suggestions waiting for manual review.",
            related_document=job.document,
        )
        if notification is not None:
            notifications.append(notification)
    return notifications


def notify_exchange_event(
    *,
    exchange: DocumentExchange,
    event_type: str,
    actor_name: str = "",
    user=None,
    comment: str = "",
) -> list[Notification]:
    if user is not None:
        return []

    notification_type_by_event = {
        "OPENED": Notification.Type.EXCHANGE_OPENED,
        "COMMENTED": Notification.Type.EXCHANGE_COMMENTED,
        "ACCEPTED": Notification.Type.EXCHANGE_ACCEPTED,
        "REJECTED": Notification.Type.EXCHANGE_REJECTED,
    }
    notification_type = notification_type_by_event.get(event_type)
    if notification_type is None:
        return []

    recipients = []
    if exchange.sent_by_id:
        recipients.append(exchange.sent_by)
    if exchange.document.uploaded_by_id:
        recipients.append(exchange.document.uploaded_by)
    if exchange.received_by_id:
        recipients.append(exchange.received_by)

    actor_label = sanitize_notification_text(actor_name or exchange.counterparty.name)
    title_by_event = {
        "OPENED": "Counterparty opened document",
        "COMMENTED": "Counterparty commented",
        "ACCEPTED": "Counterparty accepted document",
        "REJECTED": "Counterparty rejected document",
    }
    message = f"{actor_label} updated exchange for '{exchange.document.title}'."
    if event_type == "COMMENTED" and comment:
        message = f"{actor_label} commented on '{exchange.document.title}': {comment}"

    notifications = []
    for recipient in {recipient.id: recipient for recipient in recipients if recipient}.values():
        notification = create_notification(
            organization=exchange.organization,
            recipient=recipient,
            notification_type=notification_type,
            title=title_by_event[event_type],
            message=message,
            related_document=exchange.document,
            related_exchange=exchange,
        )
        if notification is not None:
            notifications.append(notification)
    return notifications


def unread_notification_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(
        recipient=user,
        organization__in=get_user_organizations(user),
        is_read=False,
    ).count()
