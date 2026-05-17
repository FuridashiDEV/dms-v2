from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from dms.models import Department, Folder, IntegrationConnection, IntegrationSyncJob
from dms.services.integrations import create_integration_sync_job
from dms.services.one_c_light import OneCLightError, import_1c_light_document


class Command(BaseCommand):
    help = "Import one local file/payload from a 1C-light scenario into a normal DMS document."

    def add_arguments(self, parser):
        parser.add_argument("--connection-id", type=int, required=True)
        parser.add_argument("--department-id", type=int, required=True)
        parser.add_argument("--file", required=True, help="Path to JSON/CSV/XML-like payload or document file.")
        parser.add_argument("--external-id", required=True)
        parser.add_argument("--object-type", default="1c_object")
        parser.add_argument("--title", default="")
        parser.add_argument("--user-id", type=int)
        parser.add_argument("--folder-id", type=int)

    def handle(self, *args, **options):
        try:
            connection = IntegrationConnection.objects.select_related("organization", "provider").get(
                pk=options["connection_id"]
            )
            department = Department.objects.select_related("organization").get(pk=options["department_id"])
        except (IntegrationConnection.DoesNotExist, Department.DoesNotExist) as exc:
            raise CommandError("Connection or department not found.") from exc

        user = None
        if options.get("user_id"):
            User = get_user_model()
            try:
                user = User.objects.get(pk=options["user_id"])
            except User.DoesNotExist as exc:
                raise CommandError("User not found.") from exc

        folder = None
        if options.get("folder_id"):
            try:
                folder = Folder.objects.get(pk=options["folder_id"])
            except Folder.DoesNotExist as exc:
                raise CommandError("Folder not found.") from exc

        sync_job = create_integration_sync_job(
            connection=connection,
            user=user,
            metadata={
                "source": "1c_light_command",
                "input_file_name": str(options["file"]).split("\\")[-1].split("/")[-1],
            },
        )

        try:
            with open(options["file"], "rb") as source:
                uploaded_file = SimpleUploadedFile(
                    str(options["file"]).split("\\")[-1].split("/")[-1],
                    source.read(),
                    content_type="application/octet-stream",
                )
            result = import_1c_light_document(
                uploaded_file=uploaded_file,
                connection=connection,
                department=department,
                folder=folder,
                external_id=options["external_id"],
                object_type=options["object_type"],
                title=options["title"],
                uploaded_by=user,
                sync_job=sync_job,
                run_ai=False,
            )
        except (OSError, OneCLightError) as exc:
            sync_job.status = IntegrationSyncJob.Status.FAILED
            sync_job.error_message = str(exc)[:2000]
            sync_job.completed_at = timezone.now()
            sync_job.save(update_fields=["status", "error_message", "completed_at"])
            raise CommandError(str(exc)) from exc

        if result.status == "rejected":
            sync_job.status = IntegrationSyncJob.Status.FAILED
            sync_job.failed_items = 1
            sync_job.error_message = result.error[:2000]
            sync_job.completed_at = timezone.now()
            sync_job.save(update_fields=["status", "failed_items", "error_message", "completed_at"])
            raise CommandError(result.error)

        self.stdout.write(
            self.style.SUCCESS(
                f"1C-light import {result.status}: external_id={result.external_id}, document_id={result.document_id}"
            )
        )
