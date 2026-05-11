# 10_1_B2B_COMMUNICATION_LAYER.md

# ПУНКТ 10.1 — B2B COMMUNICATION LAYER

## Цель

Цель этого пункта — добавить слой коммуникации между внутренними пользователями организации и внешними контактами контрагента в рамках конкретного обмена документом.

Это не полноценный real-time chat.
сообщения не существуют сами по себе
сообщения всегда относятся к конкретному DocumentExchange
Counterparty = компания-контрагент
CounterpartyContact = человек внутри компании-контрагента
ExchangeEvent фиксирует системное событие.
ExchangeMessage фиксирует текстовое содержание коммуникации.
На этом этапе нужна простая и проверяемая логика:

```text
Document
↓
DocumentExchange
↓
CounterpartyContact
↓
ExchangeMessage
↓
ExchangeEvent
↓
AuditEvent