from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from dms.services.enterprise_security import validate_production_security_settings


@dataclass(frozen=True)
class PilotCheck:
    level: str
    code: str
    message: str


REQUIRED_DOCS = (
    "docs/DEPLOYMENT.md",
    "docs/SECURITY_BASELINE.md",
    "docs/QA_CHECKLIST.md",
    "docs/PILOT_RUNBOOK.md",
    ".env.example",
)


class Command(BaseCommand):
    help = "Check pilot environment readiness without printing secrets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Return a non-zero exit code when errors or warnings are present.",
        )

    def handle(self, *args, **options):
        findings = self._collect_findings()

        if not findings:
            self.stdout.write(self.style.SUCCESS("Pilot readiness check passed."))
            return

        for finding in findings:
            line = f"{finding.level.upper()} {finding.code}: {finding.message}"
            if finding.level == "error":
                self.stdout.write(self.style.ERROR(line))
            else:
                self.stdout.write(self.style.WARNING(line))

        has_errors = any(finding.level == "error" for finding in findings)
        if has_errors or (options["strict"] and findings):
            raise SystemExit(1)

    def _collect_findings(self) -> list[PilotCheck]:
        findings: list[PilotCheck] = []
        base_dir = Path(settings.BASE_DIR)

        for security_finding in validate_production_security_settings():
            findings.append(
                PilotCheck(
                    level=security_finding.level,
                    code=f"security.{security_finding.code}",
                    message=security_finding.message,
                )
            )

        for relative_path in REQUIRED_DOCS:
            if not (base_dir / relative_path).exists():
                findings.append(
                    PilotCheck(
                        "error",
                        f"missing_doc.{relative_path.replace('/', '_')}",
                        f"Required pilot document is missing: {relative_path}",
                    )
                )

        db_password = settings.DATABASES["default"].get("PASSWORD")
        if db_password in {"", None, "12345678", "change-me"}:
            findings.append(
                PilotCheck(
                    "error",
                    "database_password_placeholder",
                    "POSTGRES_PASSWORD must be set to a non-placeholder value.",
                )
            )

        allowed_hosts = set(settings.ALLOWED_HOSTS)
        if allowed_hosts <= {"127.0.0.1", "localhost"}:
            findings.append(
                PilotCheck(
                    "warning",
                    "pilot_hosts_local_only",
                    "DJANGO_ALLOWED_HOSTS should include the pilot hostname.",
                )
            )

        if not settings.CSRF_TRUSTED_ORIGINS:
            findings.append(
                PilotCheck(
                    "warning",
                    "csrf_trusted_origins_empty",
                    "DJANGO_CSRF_TRUSTED_ORIGINS should include the pilot HTTPS origin.",
                )
            )

        if not getattr(settings, "HEALTH_CHECK_DATABASE", True):
            findings.append(
                PilotCheck(
                    "warning",
                    "database_health_disabled",
                    "HEALTH_CHECK_DATABASE should be enabled for the pilot health endpoint.",
                )
            )

        return findings
