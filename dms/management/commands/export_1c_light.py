import json

from django.core.management.base import BaseCommand, CommandError

from dms.models import Document, IntegrationConnection
from dms.services.one_c_light import OneCLightError, build_1c_light_export_payload


class Command(BaseCommand):
    help = "Print a 1C-light export payload with confirmed/applied fields only."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", type=int, required=True)
        parser.add_argument("--connection-id", type=int)

    def handle(self, *args, **options):
        try:
            document = Document.objects.get(pk=options["document_id"])
        except Document.DoesNotExist as exc:
            raise CommandError("Document not found.") from exc

        connection = None
        if options.get("connection_id"):
            try:
                connection = IntegrationConnection.objects.get(pk=options["connection_id"])
            except IntegrationConnection.DoesNotExist as exc:
                raise CommandError("Connection not found.") from exc

        try:
            payload = build_1c_light_export_payload(document=document, connection=connection)
        except OneCLightError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
