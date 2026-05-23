# Security and Governance Overview

DocFlow is designed for controlled enterprise pilots where document access and privacy matter.

## Controls

- Authentication and role-based application access.
- Organization isolation.
- Department-based visibility and explicit DocumentAccess.
- Staff-only technical diagnostics.
- Secure token hashing for external exchange links.
- AuditEvent and DocumentActivity preservation.
- Evidence exports with sensitive key redaction.
- Webhook secret redaction and private/local endpoint protection.
- Upload validation and protected file access foundation.

## Data handling

- No raw customer documents in logs.
- No tokens, passwords, API keys or server file paths in user-facing reports.
- Demo data uses synthetic entities and `example.test` addresses.

## Not claimed

- SOC2/ISO certification.
- Legal evidence certification.
- E-signature compliance.
- Automatic deletion/retention enforcement without approved policy.
