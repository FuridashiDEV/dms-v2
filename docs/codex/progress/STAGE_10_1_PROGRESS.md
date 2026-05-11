# Stage 10.1 - B2B Communication Layer

Branch: `stage-10-1-b2b-communication-layer`

## Status

Completed and verified locally.

## Scope

- Extend the existing Stage 10 `DocumentExchange` with communication contacts and messages.
- Keep messages attached to `DocumentExchange`.
- Preserve Counterparty Portal secure token flow.
- Preserve B2B Document Exchange incoming/outgoing flows.
- Do not start Stage 11.

## Implementation Plan

- Add `CounterpartyContact`.
- Add nullable `counterparty_contact` FK to `DocumentExchange`.
- Add `ExchangeMessage`.
- Add service functions for internal and external exchange messages.
- Save portal comment / accept / reject comments as `ExchangeMessage`.
- Add minimal internal and external message UI.
- Add focused tests for message persistence, permissions, and portal token behavior.

## Checks

- `makemigrations --check --dry-run`: passed.
- `manage.py check`: passed.
- `migrate --noinput` on fresh PostgreSQL: passed.
- `migrate --check`: passed.
- Stage 10.1 focused tests: passed (`4 tests`).
- Stage 9/10/10.1 regression tests: passed (`12 tests`).
- Full `dms` test suite: passed (`66 tests`).
- `git diff --check`: passed (CRLF warnings only).

## Changed Files

- `dms/models.py`
- `dms/admin.py`
- `dms/forms.py`
- `dms/services/counterparty.py`
- `dms/views.py`
- `dms/urls.py`
- `dms/migrations/0027_exchangemessage_counterpartycontact_and_more.py`
- `dms/test_b2b_communication_layer.py`
- `templates/dms/counterparty_portal.html`
- `templates/dms/document_detail.html`
- `templates/dms/exchange_list.html`
- `templates/dms/incoming_exchange_form.html`

## Manual Verification Checklist

- Existing Counterparty Portal secure links still open by token.
- Existing accept / reject / comment actions still work.
- External portal comments create `ExchangeMessage` and `ExchangeEvent`.
- Accept/reject comments are preserved as `ExchangeMessage`.
- Internal users can post messages only for accessible exchanges/documents.
- Unauthorized users cannot post internal messages to another department exchange.
- Messages remain attached to `DocumentExchange`, not a standalone chat.
- Organization and department isolation are preserved.

## Final Notes

- No WebSocket or real-time chat was added.
- No external counterparty accounts were added.
- Stage 11 was not started.

## Notes

- `docs/codex/10_1_B2B_COMMUNICATION_LAYER.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\10_1_B2B_COMMUNICATION_LAYER.md`.
