# B2B Exchange And Evidence Guide

## B2B Exchange

Status: partially implemented

The B2B exchange layer extends `DocumentExchange` around existing `Document` records. It does not create a separate document system.

Supported concepts:

- Direction: incoming or outgoing.
- Business document type or equivalent classification.
- Counterparty history through exchange list filters and related records.
- Exchange events and messages.

Routes:

- `/exchanges/`
- `/exchanges/incoming/`
- `/documents/<id>/exchanges/send/`
- `/exchanges/<exchange_id>/messages/`

## Outgoing Exchange

Status: implemented

Outgoing exchange sends an existing document to a counterparty through the secure portal. Existing document access, organization isolation, and token security still apply.

## Incoming Exchange

Status: partially implemented

Incoming exchange creates an ordinary `Document` and `DocumentVersion`. It should be reviewed like any other document upload/import. The flow is not a full EDI or Peppol network.

## Exchange Messages

Status: partially implemented

Internal and external comments are saved as `ExchangeMessage` records and linked to the exchange. Comments also create exchange events where available.

This is not a real-time chat system.

## Evidence Export

Status: partially implemented

Evidence export is available at `/documents/<id>/evidence/export/`. It produces JSON for an authorized document and collects data from existing models.

Included sections:

- Document metadata.
- Organization context.
- Document versions.
- AI processing/extracted fields where present.
- Workflow instances/actions where present.
- Exchanges, exchange events, and messages where present.
- Audit events.

Excluded data:

- Raw secure portal tokens.
- Webhook secrets.
- API keys or external credentials.
- Server file system paths.
- Unrelated organization data.

## Evidence Limitations

Status: planned

- PDF evidence package export is not implemented.
- E-signature/EDS evidence is not implemented.
- Blockchain anchoring is not implemented.
- External legal certification is not claimed.
