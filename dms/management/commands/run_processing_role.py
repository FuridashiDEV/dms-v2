from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from dms.services.processing_center import drain_processing_queue
from dms.services.processing_roles import PROCESSING_ROLES, get_processing_role


class Command(BaseCommand):
    help = "Run one Kubernetes-style AI processing role without requiring a Kubernetes cluster."

    def add_arguments(self, parser):
        parser.add_argument("--role", required=True, choices=sorted(PROCESSING_ROLES), help="Container role to run.")
        parser.add_argument("--limit", type=int, default=10, help="Jobs drained per loop.")
        parser.add_argument("--sleep-seconds", type=float, default=5.0, help="Idle sleep between loops.")
        parser.add_argument("--once", action="store_true", help="Drain once and exit, useful for tests and smoke checks.")

    def handle(self, *args, **options):
        role = get_processing_role(options["role"])
        limit = max(int(options["limit"] or 0), 0)
        sleep_seconds = max(float(options["sleep_seconds"] or 0), 0)

        if not role.stages:
            self.stdout.write(
                self.style.WARNING(
                    f"Role {role.name} has no ProcessingJob stages yet; healthcheck-only role is ready."
                )
            )
            if options["once"]:
                return
            while True:
                time.sleep(sleep_seconds)

        while True:
            results = drain_processing_queue(limit=limit, stages=role.stages)
            completed = sum(1 for result in results if result.status == "COMPLETED")
            failed_or_retry = sum(1 for result in results if result.status != "COMPLETED")
            self.stdout.write(
                f"role={role.name} stages={','.join(role.stages)} processed={len(results)} "
                f"completed={completed} failed_or_retry={failed_or_retry}"
            )
            if options["once"]:
                return
            if not results:
                time.sleep(sleep_seconds)
