# 13_SECURITY_ENTERPRISE_HARDENING.md

# ПУНКТ 13 — SECURITY / ENTERPRISE HARDENING

## Цель

Цель этого пункта — усилить безопасность существующей DMS/B2B-платформы перед реальными пилотами с бизнес-клиентами.

После предыдущих пунктов система уже умеет:

- работать с организациями;
- хранить документы;
- версионировать документы;
- записывать AuditEvent;
- обрабатывать AI-поля;
- запускать workflow;
- обмениваться документами с контрагентами;
- экспортировать evidence package;
- считать usage events;
- иметь foundation для webhooks/API.

Теперь нужно проверить и усилить безопасность.

## Главный принцип

Security hardening не должен ломать продукт.

Нужно усиливать текущую систему постепенно:

```text
existing DMS
↓
permission audit
↓
secure file access
↓
external portal hardening
↓
file validation
↓
safe logging
↓
production security checklist
Additional security findings before Stage 13:

1. Check dms/views.py around original_doc = Document.objects.get(pk=doc.pk). Confirm the document was already loaded through an access-controlled queryset before this line. If not, fix it.

2. Review token_hint display in templates/dms/document_detail.html. Decide whether token hints should be visible in normal UI. Prefer hiding it unless needed for admin/debug.

3. Review dms/services/counterparty.py where ExchangeEvent metadata stores portal_url. Avoid storing full portal URLs containing secure tokens. Store a masked URL, token hint, or no URL instead.

4. Confirm evidence export still redacts token, token_hash, token_hint, portal_url, secrets, passwords, api keys, and private keys.

Do not start new features. This is part of Security / Enterprise Hardening.