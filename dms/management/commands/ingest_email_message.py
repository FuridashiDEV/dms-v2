from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from dms.models import Department, Folder, IntegrationConnection, IntegrationSyncJob
from dms.services.email_ingestion import EmailIngestionError, ingest_email_message_from_file
from dms.services.integrations import create_integration_sync_job


class Command(BaseCommand):
    help = "Ingest attachments from a single .eml message into normal DMS documents."

    def add_arguments(self, parser):
        parser.add_argument("--connection-id", type=int, required=True)
        parser.add_argument("--department-id", type=int, required=True)
        parser.add_argument("--file", required=True, help="Path to a .eml file.")
        parser.add_argument("--user-id", type=int)
        parser.add_argument("--folder-id", type=int)

    def handle(self, *args, **options):
        try:
            connection = IntegrationConnection.objects.select_related("organization", "provider").get(
                pk=options["connection_id"]
            )
        except IntegrationConnection.DoesNotExist as exc:
            raise CommandError("Integration connection not found.") from exc

        try:
            department = Department.objects.select_related("organization").get(pk=options["department_id"])
        except Department.DoesNotExist as exc:
            raise CommandError("Department not found.") from exc

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
                "source": "email_ingestion_command",
                "input_file_name": str(options["file"]).split("\\")[-1].split("/")[-1],
            },
        )

        try:
            result = ingest_email_message_from_file(
                file_path=options["file"],
                connection=connection,
                department=department,
                folder=folder,
                uploaded_by=user,
                sync_job=sync_job,
                run_ai=False,
            )
        except (OSError, EmailIngestionError) as exc:
            sync_job.status = IntegrationSyncJob.Status.FAILED
            sync_job.error_message = str(exc)[:2000]
            sync_job.completed_at = timezone.now()
            sync_job.save(update_fields=["status", "error_message", "completed_at"])
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Email ingestion completed: "
                f"attachments={result.total_attachments}, "
                f"created={result.created_documents}, "
                f"duplicates={result.skipped_duplicates}, "
                f"rejected={result.rejected_attachments}"
            )
        )
