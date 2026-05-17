from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dms.models import Organization, ProcessingProfile
from dms.services.processing_center import drain_processing_queue, get_or_create_default_processing_profile


class Command(BaseCommand):
    help = "Drain the local AI processing foundation queue without replacing upload/search flows."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Maximum jobs to execute in this run.")
        parser.add_argument("--organization-id", type=int, default=None, help="Restrict processing to one organization.")
        parser.add_argument("--profile-code", default="", help="Restrict processing to a processing profile code.")

    def handle(self, *args, **options):
        limit = max(int(options["limit"] or 0), 0)
        organization = None
        if options["organization_id"]:
            try:
                organization = Organization.objects.get(id=options["organization_id"])
            except Organization.DoesNotExist as exc:
                raise CommandError("Organization not found.") from exc

        profile = None
        profile_code = (options.get("profile_code") or "").strip()
        if profile_code:
            profile_qs = ProcessingProfile.objects.filter(code=profile_code)
            if organization is not None:
                profile_qs = profile_qs.filter(organization=organization)
            else:
                profile_qs = profile_qs.filter(organization__isnull=True)
            profile = profile_qs.first()
            if profile is None:
                raise CommandError("Processing profile not found.")
        elif organization is not None:
            profile = get_or_create_default_processing_profile(organization)

        results = drain_processing_queue(limit=limit, profile=profile, organization=organization)
        completed = sum(1 for result in results if result.status == "COMPLETED")
        failed_or_retry = sum(1 for result in results if result.status != "COMPLETED")
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {len(results)} jobs: completed={completed}, failed_or_retry={failed_or_retry}."
            )
        )
