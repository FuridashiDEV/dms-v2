from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from dms.models import ProcessingJob
from dms.services.disaster_recovery import (
    mark_processing_job_dead_letter,
    recover_stuck_processing_jobs,
    restart_processing_job,
)


class Command(BaseCommand):
    help = "Recover stuck processing jobs or manually restart/dead-letter a processing job."

    def add_arguments(self, parser):
        parser.add_argument("--older-than-minutes", type=int, default=getattr(settings, "DMS_PROCESSING_STUCK_JOB_MINUTES", 30))
        parser.add_argument("--organization-id", type=int, default=None)
        parser.add_argument("--stage", action="append", dest="stages", help="Limit stuck-job recovery to a pipeline stage.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--restart-job-id", type=int, default=None)
        parser.add_argument("--dead-letter-job-id", type=int, default=None)
        parser.add_argument("--keep-attempts", action="store_true", help="Do not reset attempt_count on manual restart.")

    def handle(self, *args, **options):
        restart_job_id = options["restart_job_id"]
        dead_letter_job_id = options["dead_letter_job_id"]
        if restart_job_id and dead_letter_job_id:
            raise CommandError("Use only one manual action at a time.")

        if restart_job_id:
            job = self._get_job(restart_job_id)
            if options["dry_run"]:
                self.stdout.write(f"dry-run restart job={job.id} status={job.status}")
                return
            result = restart_processing_job(job, reset_attempts=not options["keep_attempts"])
            self.stdout.write(self.style.SUCCESS(self._format_result(result)))
            return

        if dead_letter_job_id:
            job = self._get_job(dead_letter_job_id)
            if options["dry_run"]:
                self.stdout.write(f"dry-run dead-letter job={job.id} status={job.status}")
                return
            result = mark_processing_job_dead_letter(job)
            self.stdout.write(self.style.SUCCESS(self._format_result(result)))
            return

        results = recover_stuck_processing_jobs(
            older_than_minutes=options["older_than_minutes"],
            organization_id=options["organization_id"],
            stages=options["stages"] or None,
            dry_run=options["dry_run"],
        )
        if not results:
            self.stdout.write(self.style.SUCCESS("No stuck processing jobs found."))
            return

        for result in results:
            line = self._format_result(result)
            self.stdout.write(f"dry-run {line}" if options["dry_run"] else line)
        self.stdout.write(self.style.SUCCESS(f"Recovered {len(results)} processing job(s)."))

    def _get_job(self, job_id: int) -> ProcessingJob:
        try:
            return ProcessingJob.objects.get(id=job_id)
        except ProcessingJob.DoesNotExist as exc:
            raise CommandError(f"Processing job {job_id} was not found.") from exc

    def _format_result(self, result) -> str:
        return (
            f"job={result.job_id} action={result.action} "
            f"from={result.previous_status} to={result.status} reason={result.reason}"
        )
