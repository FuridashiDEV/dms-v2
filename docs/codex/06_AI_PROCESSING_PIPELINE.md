# 06_AI_PROCESSING_PIPELINE.md

# ПУНКТ 6 — AI PROCESSING PIPELINE И РУЧНАЯ ПРОВЕРКА AI-РЕЗУЛЬТАТОВ

## Цель

Цель этого пункта — превратить текущую AI-обработку документов в контролируемый, проверяемый и редактируемый пайплайн.

Сейчас в проекте уже может быть:

- извлечение текста из файла;
- AI parser;
- определение title;
- определение description;
- определение doc_date;
- определение doc_type;
- embeddings / semantic search.

На этом пункте нельзя переписывать AI полностью.

Нужно обернуть существующую AI-логику в управляемую структуру:

```text
Document
↓
ProcessingJob
↓
ExtractedField suggestions
↓
Human validation
↓
Apply confirmed values to Document