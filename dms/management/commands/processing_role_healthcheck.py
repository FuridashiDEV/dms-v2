from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connections

from dms.services.processing_roles import PROCESSING_ROLES, get_processing_role


class Command(BaseCommand):
    help = "Lightweight healthcheck for Kubernetes scheduler/worker containers."

    def add_arguments(self, parser):
        parser.add_argument("--role", required=True, choices=sorted(PROCESSING_ROLES), help="Container role to check.")
        parser.add_argument("--skip-db", action="store_true", help="Only validate the role mapping.")

    def handle(self, *args, **options):
        role = get_processing_role(options["role"])
        if not options["skip_db"]:
            connections["default"].ensure_connection()
        self.stdout.write(self.style.SUCCESS(f"ok role={role.name} stages={','.join(role.stages) or 'none'}"))
