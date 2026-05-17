from __future__ import annotations

from django.core.management.base import BaseCommand

from dms.models import Document
from dms.services.document_indexing import build_document_index_chunks, index_document
from dms.services.index_versions import get_active_search_index_version, is_document_index_stale


class Command(BaseCommand):
    help = "Rebuild normalized search metadata and Qdrant vectors for documents."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", type=int, help="Reindex one document only.")
        parser.add_argument("--organization-id", type=int, help="Limit reindexing to one organization.")
        parser.add_argument("--limit", type=int, help="Limit the number of documents processed.")
        parser.add_argument(
            "--only-stale",
            action="store_true",
            help="Only reindex documents missing a current DocumentSearchIndexState or with stale index fingerprint.",
        )

    def handle(self, *args, **options):
        queryset = Document.objects.select_related("organization", "department", "folder", "doc_type").order_by("id")

        if options.get("document_id"):
            queryset = queryset.filter(id=options["document_id"])
        if options.get("organization_id"):
            queryset = queryset.filter(organization_id=options["organization_id"])
        if options.get("limit"):
            queryset = queryset[: options["limit"]]

        index_version = get_active_search_index_version()
        total = 0
        indexed = 0
        skipped = 0
        for document in queryset:
            total += 1
            if options.get("only_stale") and not is_document_index_stale(
                document,
                index_version=index_version,
                chunks=build_document_index_chunks(document),
            ):
                skipped += 1
                continue
            if index_document(document):
                indexed += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Search reindex complete. total={total} indexed={indexed} skipped={skipped}"
            )
        )
