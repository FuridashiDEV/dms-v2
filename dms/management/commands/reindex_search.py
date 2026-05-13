from __future__ import annotations

from django.core.management.base import BaseCommand

from dms.models import Document
from dms.services.document_indexing import index_document


class Command(BaseCommand):
    help = "Rebuild normalized search metadata and Qdrant vectors for documents."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", type=int, help="Reindex one document only.")
        parser.add_argument("--organization-id", type=int, help="Limit reindexing to one organization.")
        parser.add_argument("--limit", type=int, help="Limit the number of documents processed.")
        parser.add_argument(
            "--only-stale",
            action="store_true",
            help="Only reindex documents without current search metadata.",
        )

    def handle(self, *args, **options):
        queryset = Document.objects.select_related("organization", "department", "folder", "doc_type").order_by("id")

        if options.get("document_id"):
            queryset = queryset.filter(id=options["document_id"])
        if options.get("organization_id"):
            queryset = queryset.filter(organization_id=options["organization_id"])
        if options.get("only_stale"):
            queryset = queryset.filter(search_indexed_at__isnull=True)
        if options.get("limit"):
            queryset = queryset[: options["limit"]]

        total = 0
        indexed = 0
        skipped = 0
        for document in queryset:
            total += 1
            if index_document(document):
                indexed += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Search reindex complete. total={total} indexed={indexed} skipped={skipped}"
            )
        )
