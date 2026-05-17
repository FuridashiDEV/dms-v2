from django.core.management.base import BaseCommand

from dms.services.enterprise_security import validate_production_security_settings


class Command(BaseCommand):
    help = "Validate production security settings without printing secrets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-warning",
            action="store_true",
            help="Return a non-zero exit code when warnings are present.",
        )

    def handle(self, *args, **options):
        findings = validate_production_security_settings()
        errors = [finding for finding in findings if finding.level == "error"]
        warnings = [finding for finding in findings if finding.level == "warning"]

        if not findings:
            self.stdout.write(self.style.SUCCESS("Production security settings validation passed."))
            return

        for finding in findings:
            line = f"{finding.level.upper()} {finding.code}: {finding.message}"
            if finding.level == "error":
                self.stdout.write(self.style.ERROR(line))
            else:
                self.stdout.write(self.style.WARNING(line))

        if errors or (warnings and options["fail_on_warning"]):
            raise SystemExit(1)
