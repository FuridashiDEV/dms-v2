# 03_ORGANIZATION_TENANCY.md

# ПУНКТ 3 — ORGANIZATION / MULTI-TENANCY FOUNDATION

## Цель

Цель этого пункта — добавить верхний уровень Organization, чтобы существующая DMS-система могла в будущем работать как SaaS-платформа для нескольких организаций.

Это фундаментальный этап для будущих функций:

- B2B;
- B2B2B;
- counterparty portal;
- document exchange;
- usage tracking;
- billing;
- enterprise isolation.

## Главный принцип

Нельзя создавать новую систему рядом со старой.

Organization должна нарастить существующую структуру:

```text
Organization
  └── Department
        └── Folder
        └── Document
        └── User access