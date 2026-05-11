# Admin Guide

## Django Admin

Status: implemented

Django admin is available at `/admin/` for staff/superuser accounts. The project registers operational models for documents, organizations, audit, usage, workflow, exchange, integration, and billing foundations.

## Organization And User Administration

Status: implemented

Relevant models:

- `Organization`
- `OrganizationMember`
- `Department`
- User model and role fields
- `DocumentAccess`

Internal user management routes include `/users/`, `/users/create/`, `/users/<id>/password/`, and `/users/<id>/delete/`. These routes are intended for the existing internal admin model, not public registration.

## Document Administration

Status: implemented

Relevant models:

- `Document`
- `DocumentVersion`
- `DocumentType`
- `DocumentRelation`
- `DocumentActivity`
- `DocumentAccess`

Admin users should keep document organization and department values aligned. Cross-organization access must not be created manually.

## Audit And Usage

Status: implemented

Relevant models:

- `AuditEvent`
- `UsageEvent`

Audit events record security and business actions. Usage events are product usage records and should not be treated as billing invoices.

The usage dashboard is available at `/usage/`.

## Workflow Administration

Status: partially implemented

Relevant models:

- `WorkflowTemplate`
- `WorkflowStepTemplate`
- `WorkflowInstance`
- `WorkflowAction`

Templates and steps can be configured through admin. Runtime approvals remain a simple MVP flow and should be tested with the exact approver assignments before pilot use.

## Counterparty And Exchange Administration

Status: partially implemented

Relevant models:

- `Counterparty`
- `CounterpartyContact`
- `DocumentExchange`
- `ExchangeEvent`
- `ExchangeMessage`

Secure external portal tokens must not be copied into tickets, logs, docs, or support notes. Use exchange status and events for support investigation.

## Integrations

Status: foundation only

Relevant models:

- `IntegrationProvider`
- `IntegrationConnection`
- `IntegrationSyncJob`
- `ExternalReference`

The integration layer tracks providers, connections, sync jobs, and external references. It does not perform real OAuth or live third-party synchronization.

## Billing And Quotas

Status: foundation only

Relevant models:

- `Plan`
- `PlanQuota`
- `Subscription`

Billing data is read-only foundation data. No payment gateway, real invoices, or hard usage blocking are implemented.

## Analytics

Status: partially implemented

Analytics is available at `/analytics/`. Superusers can see platform-level metrics. Organization users are limited to organization-level metrics.

## Operational Responsibilities

- Keep `.env` out of Git.
- Use `/health/` for basic service health.
- Follow [Deployment Runbook](DEPLOYMENT.md) for Docker, backup, and restore.
- Follow [QA Checklist](QA_CHECKLIST.md) before merging stage branches or preparing demos.
