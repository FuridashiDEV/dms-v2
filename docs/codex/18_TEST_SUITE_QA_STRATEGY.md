# 18_TEST_SUITE_QA_STRATEGY.md

# ПУНКТ 18 — TEST SUITE / QA STRATEGY: СИСТЕМНОЕ ТЕСТИРОВАНИЕ И ЗАЩИТА ОТ РЕГРЕССИЙ

## Цель

Цель этого пункта — усилить тестовое покрытие и QA-процесс проекта после поэтапной эволюции DMS в B2B/B2B2B-платформу.

На этом пункте нельзя добавлять новые продуктовые функции.

Нужно проверить и защитить уже реализованные слои:

- users / roles;
- organizations;
- departments;
- documents;
- document versions;
- audit events;
- AI processing;
- import layer;
- workflow;
- counterparty portal;
- B2B exchange;
- evidence export;
- usage tracking;
- integrations;
- billing foundation;
- analytics;
- security hardening.

## Главный принцип

Тесты должны защищать текущую рабочую систему.

Нельзя переписывать проект ради тестов.

Правильная логика:

```text
existing product flows
↓
critical regression tests
↓
permission tests
↓
manual QA checklist
↓
future development becomes safer