from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dms.services.load_testing import (
    DEFAULT_SAFE_EXECUTE_LIMIT,
    LOAD_PROFILES,
    get_load_profile,
    run_load_profile,
    write_load_report,
)


class Command(BaseCommand):
    help = "Run a synthetic load-testing profile in dry-run mode by default."

    def add_arguments(self, parser):
        parser.add_argument("--profile", required=True, choices=sorted(LOAD_PROFILES), help="Load profile to run.")
        parser.add_argument("--dry-run", action="store_true", help="Generate an estimate/report without DB writes.")
        parser.add_argument("--execute", action="store_true", help="Actually create synthetic load-test records.")
        parser.add_argument("--allow-heavy", action="store_true", help="Allow execute mode above the safe local limit.")
        parser.add_argument("--limit", type=int, default=None, help="Override profile document count for a small run.")
        parser.add_argument("--batch-size", type=int, default=None, help="Override profile batch size.")
        parser.add_argument("--organization-slug", default="load-test-synthetic")
        parser.add_argument("--include-queue", action="store_true", help="Also create synthetic ProcessingJob backlog in execute mode.")
        parser.add_argument("--queue-jobs", type=int, default=None, help="Override queue jobs count for execute mode.")
        parser.add_argument("--report", default=None, help="Write JSON report to this path.")

    def handle(self, *args, **options):
        profile = get_load_profile(options["profile"])
        if options["execute"] and options["dry_run"]:
            raise CommandError("Use either --dry-run or --execute, not both.")

        dry_run = not options["execute"]
        target_count = int(options["limit"] or profile.document_count)
        if target_count < 0:
            raise CommandError("--limit must be positive.")
        if not dry_run and target_count > DEFAULT_SAFE_EXECUTE_LIMIT and not options["allow_heavy"]:
            raise CommandError(
                f"Refusing to create {target_count} records without --allow-heavy. "
                f"Use --limit {DEFAULT_SAFE_EXECUTE_LIMIT} or less for local smoke tests."
            )

        report = run_load_profile(
            profile_name=profile.name,
            dry_run=dry_run,
            limit=target_count,
            organization_slug=options["organization_slug"],
            include_queue=options["include_queue"],
            queue_jobs=options["queue_jobs"],
            batch_size=options["batch_size"],
        )
        output_path = write_load_report(report, options["report"])

        mode = "dry-run" if dry_run else "execute"
        self.stdout.write(
            self.style.SUCCESS(
                f"Load profile {profile.name} completed in {mode} mode: "
                f"requested={report['requested_documents']} "
                f"created={report['actual_created_documents']} "
                f"queue_jobs={report['actual_created_queue_jobs']} "
                f"report={output_path}"
            )
        )
