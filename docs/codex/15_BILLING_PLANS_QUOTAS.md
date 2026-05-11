# 15_BILLING_PLANS_QUOTAS.md

# ПУНКТ 15 — BILLING / PLANS / QUOTAS FOUNDATION

## Цель

Цель этого пункта — добавить foundation для будущей монетизации продукта.

После предыдущих пунктов система уже должна уметь:

- работать с организациями;
- хранить документы;
- обрабатывать AI-поля;
- запускать workflow;
- обмениваться документами с контрагентами;
- экспортировать evidence package;
- считать UsageEvent;
- иметь integration foundation.

Теперь нужно добавить слой тарифов и лимитов.

Важно:

На этом пункте НЕ нужно подключать реальные платежи.

Нужно только подготовить внутреннюю структуру:

```text
Organization
↓
Subscription
↓
Plan
↓
Quota
↓
UsageEvent
↓
Monthly usage summary