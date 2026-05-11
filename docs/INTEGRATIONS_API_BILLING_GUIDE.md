# Integrations, API, Webhooks, And Billing Guide

## Usage Tracking

Status: implemented

`UsageEvent` records product usage for key flows. The usage dashboard is available at `/usage/`.

Usage records are telemetry for reporting and quota comparison. They are not invoices.

## Webhooks

Status: foundation only

Models:

- `WebhookEndpoint`
- `WebhookDelivery`

Webhook delivery is a queued foundation. Secrets are stored as hashes and must not be logged or exposed. The project does not provide a full webhook management UI or production delivery worker in this stage.

## API

Status: foundation only

The project exposes Django web routes for product flows. It does not implement a full public REST API, full developer portal, OAuth app management, or broad API key lifecycle.

Any route that returns JSON should be treated as an internal app endpoint unless explicitly documented otherwise.

## Integrations

Status: foundation only

Models:

- `IntegrationProvider`
- `IntegrationConnection`
- `IntegrationSyncJob`
- `ExternalReference`

The integration service can seed standard providers and link external references to existing documents. Real OAuth, real access token storage, and live sync with Google Drive, OneDrive, SharePoint, 1C, Peppol, EDI, or EDS are not implemented.

Credentials must not be stored in plain JSON. Use the existing credential metadata/hash fields and environment-backed secrets when a real integration is added later.

## Billing, Plans, And Quotas

Status: foundation only

Models:

- `Plan`
- `PlanQuota`
- `Subscription`

The billing foundation supports basic plan and quota data plus monthly usage aggregation from `UsageEvent`.

Not implemented:

- Payment gateway.
- Stripe, Kaspi, CloudPayments, or another payment provider.
- Real invoices.
- Automatic user blocking when limits are exceeded.
- Complex accounting.

## Analytics

Status: partially implemented

Analytics is available at `/analytics/`. Superusers can see platform-level metrics. Organization users can see organization-level metrics only. Date range filtering is available.

This is an internal dashboard, not an external analytics SDK or data warehouse.
