# 08_WORKFLOW_ENGINE_MVP.md

# ПУНКТ 8 — WORKFLOW ENGINE MVP: СОГЛАСОВАНИЕ ДОКУМЕНТОВ

## Цель

Цель этого пункта — добавить базовый workflow engine для согласования документов внутри организации.

Workflow должен работать поверх существующего `Document`.

Нельзя создавать отдельную систему документов.

Нельзя строить сложный BPMN / no-code workflow builder на этом этапе.

Нужно реализовать простой, понятный и проверяемый MVP:

```text
Document
↓
WorkflowTemplate
↓
WorkflowInstance
↓
WorkflowAction
↓
Document.status changes
↓
AuditEvent records actions