# Counterparty Portal Guide

## Scope

Status: partially implemented

The counterparty portal is a token-based external page for a single `DocumentExchange`. It is not a full external account system, supplier network, or public registration flow.

## Internal Send Flow

Status: implemented

An authorized internal user sends a document from `/documents/<id>/exchanges/send/`. The flow creates or uses a `Counterparty`, creates a `DocumentExchange`, records exchange events, and exposes a secure portal URL for that exchange.

Internal permissions are still enforced. Users cannot send documents they cannot access.

## External Portal

Status: partially implemented

External counterparties use:

- `/portal/exchanges/<token>/` to view the exchange page.
- `/portal/exchanges/<token>/download/` to download the exchanged document.
- `/portal/exchanges/<token>/<action>/` to accept, reject, or comment where the action is supported.

The token scopes access to one exchange only. The portal does not expose internal navigation, organization data, raw token hashes, or unrelated documents.

## External Actions

Status: implemented

Supported external actions:

- Accept
- Reject
- Comment
- Download

Accept/reject comments are saved into exchange history. The B2B communication layer stores messages on the related exchange.

## Contacts And Messages

Status: partially implemented

`CounterpartyContact` and `ExchangeMessage` support basic contact and message tracking around an exchange. This is not a real-time chat product and does not create full external user accounts.

## Security Notes

- Never publish portal tokens in logs, issue trackers, public docs, or emails beyond the intended counterparty delivery channel.
- Treat portal links as sensitive.
- Rotate or recreate an exchange if a portal link is exposed to the wrong party.
- Use internal document permissions before sending a document externally.

## Not Implemented

Status: planned

- External account registration.
- Supplier onboarding/network.
- E-signature or EDS.
- Peppol/EDI transport.
- Real-time chat/WebSocket messaging.
