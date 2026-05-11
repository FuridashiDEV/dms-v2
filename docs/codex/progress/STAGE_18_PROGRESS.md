# Stage 18 - Test Suite / QA Strategy

Branch: `stage-18-test-suite-qa-strategy`

## Status

Completed.

## Scope

- Audit current tests.
- Add safe test helpers where useful.
- Add regression, permission, organization-isolation, and security tests for existing flows.
- Add `docs/QA_CHECKLIST.md` and `docs/TESTING.md`.
- Do not add product features, change business logic for tests, rewrite the test framework, or start Stage 19.

## Checks

- `.\\.venv\\Scripts\\python.exe manage.py check` - passed.
- `.\\.venv\\Scripts\\python.exe manage.py makemigrations --check --dry-run` - passed, no changes detected.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_qa_regression_strategy --verbosity 2` - passed, 4 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms.test_qa_regression_strategy dms.test_security_enterprise_hardening dms.test_security_flows dms.test_organization_tenancy dms.test_product_analytics_dashboard dms.test_devops_foundation --verbosity 1` - passed, 25 tests.
- `.\\.venv\\Scripts\\python.exe manage.py test dms --verbosity 1` - passed, 101 tests.

## Implemented

- Audited existing Django `TestCase` suite and stage-specific test files.
- Added lightweight test factories in `dms/test_factories.py`.
- Added consolidated QA regression tests for document creation service, audit/usage/version chain, protected routes, unauthenticated redirects, and organization isolation.
- Added `docs/QA_CHECKLIST.md`.
- Added `docs/TESTING.md`.

## Notes

- `docs/codex/18_TEST_SUITE_QA_STRATEGY.md` is not present in the repository; the stage file was read from `C:\Users\Smart Product\Desktop\dmsv2\правила\18_TEST_SUITE_QA_STRATEGY.md`.
- No product features, migrations, heavy test dependencies, test framework rewrite, or Stage 19 work was added.
