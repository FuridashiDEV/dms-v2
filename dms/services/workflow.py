from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from dms.models import (
    AuditEvent,
    Document,
    DocumentActivity,
    WorkflowAction,
    WorkflowInstance,
    WorkflowStepTemplate,
    WorkflowTemplate,
)
from dms.services.audit import record_audit_event
from dms.utils import get_allowed_departments, user_can_access_document


class WorkflowError(ValueError):
    pass


class WorkflowPermissionError(PermissionError):
    pass


def can_start_workflow(user, document: Document) -> bool:
    if not user_can_access_document(user, document):
        return False
    if user.role == "ADMIN":
        return True
    if document.uploaded_by_id == user.id:
        return True
    return get_allowed_departments(user).filter(id=document.department_id).exists()


def can_act_on_workflow(user, instance: WorkflowInstance) -> bool:
    document = instance.document
    if not user_can_access_document(user, document):
        return False
    if user.role == "ADMIN":
        return True

    step = instance.current_step_template
    if step is None:
        return False
    if step.approver_user_id and step.approver_user_id == user.id:
        return True
    if step.approver_department_id:
        return get_allowed_departments(user).filter(
            id=step.approver_department_id,
        ).exists()
    return False


def get_active_workflow(document: Document) -> WorkflowInstance | None:
    return (
        document.workflow_instances
        .select_related(
            "template",
            "current_step_template",
            "current_step_template__approver_user",
            "current_step_template__approver_department",
        )
        .filter(status=WorkflowInstance.Status.ACTIVE)
        .order_by("-started_at")
        .first()
    )


def _first_step(template: WorkflowTemplate) -> WorkflowStepTemplate | None:
    return template.steps.order_by("order", "id").first()


def _next_step(step: WorkflowStepTemplate) -> WorkflowStepTemplate | None:
    return (
        step.template.steps
        .filter(order__gt=step.order)
        .order_by("order", "id")
        .first()
    )


def _set_document_status(document: Document, status: str, *, user):
    if document.status == status:
        return None
    document.status = status
    document.save(update_fields=["status"])
    return document.create_version(uploaded_by=user)


def _record_action(
    *,
    instance: WorkflowInstance,
    actor,
    action_type: str,
    comment: str = "",
) -> WorkflowAction:
    return WorkflowAction.objects.create(
        organization=instance.organization,
        instance=instance,
        document=instance.document,
        step_template=instance.current_step_template,
        actor=actor,
        action_type=action_type,
        comment=comment or "",
    )


def _record_activity(*, document: Document, user, action: str):
    if user and getattr(user, "is_authenticated", False):
        DocumentActivity.objects.create(
            user=user,
            document=document,
            action=action,
        )


def _audit(
    *,
    event_type: str,
    instance: WorkflowInstance,
    action: WorkflowAction | None,
    request=None,
    document_version=None,
    metadata: dict | None = None,
):
    data = {
        "workflow_instance_id": instance.id,
        "workflow_template_id": instance.template_id,
        "workflow_status": instance.status,
        "workflow_step_template_id": instance.current_step_template_id,
    }
    if action is not None:
        data.update(
            {
                "workflow_action_id": action.id,
                "workflow_action_type": action.action_type,
            }
        )
    if metadata:
        data.update(metadata)
    return record_audit_event(
        event_type=event_type,
        request=request,
        document=instance.document,
        document_version=document_version,
        metadata=data,
    )


@transaction.atomic
def start_workflow(
    *,
    document: Document,
    template: WorkflowTemplate,
    user,
    request=None,
    comment: str = "",
) -> WorkflowInstance:
    document = Document.objects.select_for_update().get(pk=document.pk)
    template = WorkflowTemplate.objects.prefetch_related("steps").get(pk=template.pk)

    if template.organization_id != document.organization_id:
        raise WorkflowError("Workflow template belongs to another organization.")
    if not template.is_active:
        raise WorkflowError("Workflow template is inactive.")
    if not can_start_workflow(user, document):
        raise WorkflowPermissionError("User cannot start workflow for this document.")
    if get_active_workflow(document) is not None:
        raise WorkflowError("Document already has an active workflow.")

    first_step = _first_step(template)
    if first_step is None:
        raise WorkflowError("Workflow template has no steps.")

    previous_status = document.status
    instance = WorkflowInstance.objects.create(
        organization=document.organization,
        document=document,
        template=template,
        current_step_template=first_step,
        started_by=user,
        status=WorkflowInstance.Status.ACTIVE,
    )
    version = _set_document_status(document, Document.Status.IN_REVIEW, user=user)
    action = _record_action(
        instance=instance,
        actor=user,
        action_type=WorkflowAction.ActionType.START,
        comment=comment,
    )
    _record_activity(
        document=document,
        user=user,
        action=DocumentActivity.ACTION_WORKFLOW_STARTED,
    )
    _audit(
        event_type=AuditEvent.EventType.WORKFLOW_STARTED,
        instance=instance,
        action=action,
        request=request,
        document_version=version,
        metadata={
            "previous_status": previous_status,
            "new_status": document.status,
        },
    )
    return instance


@transaction.atomic
def approve_workflow(
    *,
    instance: WorkflowInstance,
    user,
    request=None,
    comment: str = "",
) -> WorkflowInstance:
    instance = (
        WorkflowInstance.objects
        .select_for_update(of=("self",))
        .select_related("document", "template")
        .get(pk=instance.pk)
    )
    if instance.status != WorkflowInstance.Status.ACTIVE:
        raise WorkflowError("Workflow is not active.")
    if not can_act_on_workflow(user, instance):
        raise WorkflowPermissionError("User cannot approve this workflow step.")

    current_step = instance.current_step_template
    next_step = _next_step(current_step)
    previous_status = instance.document.status
    action = _record_action(
        instance=instance,
        actor=user,
        action_type=WorkflowAction.ActionType.APPROVE,
        comment=comment,
    )

    document_version = None
    if next_step is None:
        instance.status = WorkflowInstance.Status.APPROVED
        instance.current_step_template = None
        instance.completed_at = timezone.now()
        instance.save(update_fields=["status", "current_step_template", "completed_at"])
        document_version = _set_document_status(
            instance.document,
            Document.Status.APPROVED,
            user=user,
        )
        _record_activity(
            document=instance.document,
            user=user,
            action=DocumentActivity.ACTION_WORKFLOW_APPROVED,
        )
        _audit(
            event_type=AuditEvent.EventType.WORKFLOW_COMPLETED,
            instance=instance,
            action=action,
            request=request,
            document_version=document_version,
            metadata={
                "previous_status": previous_status,
                "new_status": instance.document.status,
                "decision": "approved",
            },
        )
    else:
        instance.current_step_template = next_step
        instance.save(update_fields=["current_step_template"])
        _record_activity(
            document=instance.document,
            user=user,
            action=DocumentActivity.ACTION_WORKFLOW_APPROVED,
        )

    _audit(
        event_type=AuditEvent.EventType.WORKFLOW_APPROVED,
        instance=instance,
        action=action,
        request=request,
        document_version=document_version,
        metadata={
            "approved_step_template_id": current_step.id if current_step else None,
            "next_step_template_id": next_step.id if next_step else None,
        },
    )
    return instance


@transaction.atomic
def reject_workflow(
    *,
    instance: WorkflowInstance,
    user,
    request=None,
    comment: str = "",
) -> WorkflowInstance:
    instance = (
        WorkflowInstance.objects
        .select_for_update(of=("self",))
        .select_related("document", "template")
        .get(pk=instance.pk)
    )
    if instance.status != WorkflowInstance.Status.ACTIVE:
        raise WorkflowError("Workflow is not active.")
    if not can_act_on_workflow(user, instance):
        raise WorkflowPermissionError("User cannot reject this workflow step.")

    previous_status = instance.document.status
    action = _record_action(
        instance=instance,
        actor=user,
        action_type=WorkflowAction.ActionType.REJECT,
        comment=comment,
    )
    instance.status = WorkflowInstance.Status.REJECTED
    instance.current_step_template = None
    instance.completed_at = timezone.now()
    instance.save(update_fields=["status", "current_step_template", "completed_at"])
    version = _set_document_status(instance.document, Document.Status.REJECTED, user=user)
    _record_activity(
        document=instance.document,
        user=user,
        action=DocumentActivity.ACTION_WORKFLOW_REJECTED,
    )
    _audit(
        event_type=AuditEvent.EventType.WORKFLOW_REJECTED,
        instance=instance,
        action=action,
        request=request,
        document_version=version,
        metadata={
            "previous_status": previous_status,
            "new_status": instance.document.status,
        },
    )
    return instance


@transaction.atomic
def request_workflow_changes(
    *,
    instance: WorkflowInstance,
    user,
    request=None,
    comment: str = "",
) -> WorkflowInstance:
    instance = (
        WorkflowInstance.objects
        .select_for_update(of=("self",))
        .select_related("document", "template")
        .get(pk=instance.pk)
    )
    if instance.status != WorkflowInstance.Status.ACTIVE:
        raise WorkflowError("Workflow is not active.")
    if not can_act_on_workflow(user, instance):
        raise WorkflowPermissionError("User cannot request changes for this workflow step.")

    previous_status = instance.document.status
    action = _record_action(
        instance=instance,
        actor=user,
        action_type=WorkflowAction.ActionType.REQUEST_CHANGES,
        comment=comment,
    )
    instance.status = WorkflowInstance.Status.CHANGES_REQUESTED
    instance.current_step_template = None
    instance.completed_at = timezone.now()
    instance.save(update_fields=["status", "current_step_template", "completed_at"])
    version = _set_document_status(
        instance.document,
        Document.Status.CHANGES_REQUESTED,
        user=user,
    )
    _record_activity(
        document=instance.document,
        user=user,
        action=DocumentActivity.ACTION_WORKFLOW_CHANGES_REQUESTED,
    )
    _audit(
        event_type=AuditEvent.EventType.WORKFLOW_CHANGES_REQUESTED,
        instance=instance,
        action=action,
        request=request,
        document_version=version,
        metadata={
            "previous_status": previous_status,
            "new_status": instance.document.status,
        },
    )
    return instance


@transaction.atomic
def comment_workflow(
    *,
    instance: WorkflowInstance,
    user,
    request=None,
    comment: str,
) -> WorkflowAction:
    instance = (
        WorkflowInstance.objects
        .select_for_update(of=("self",))
        .select_related("document", "template")
        .get(pk=instance.pk)
    )
    if instance.status != WorkflowInstance.Status.ACTIVE:
        raise WorkflowError("Workflow is not active.")
    if not can_act_on_workflow(user, instance):
        raise WorkflowPermissionError("User cannot comment on this workflow step.")
    if not comment:
        raise WorkflowError("Comment is required.")

    action = _record_action(
        instance=instance,
        actor=user,
        action_type=WorkflowAction.ActionType.COMMENT,
        comment=comment,
    )
    _record_activity(
        document=instance.document,
        user=user,
        action=DocumentActivity.ACTION_WORKFLOW_COMMENTED,
    )
    _audit(
        event_type=AuditEvent.EventType.WORKFLOW_COMMENTED,
        instance=instance,
        action=action,
        request=request,
    )
    return action
