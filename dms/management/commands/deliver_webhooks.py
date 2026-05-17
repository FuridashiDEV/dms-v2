from django.core.management.base import BaseCommand, CommandError

from dms.models import WebhookDelivery
from dms.services.webhooks import send_due_webhook_deliveries, send_webhook_delivery


class Command(BaseCommand):
    help = "Deliver pending webhook notifications to external endpoints."

    def add_arguments(self, parser):
        parser.add_argument("--delivery-id", type=int)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-attempts", type=int)
        parser.add_argument("--timeout", type=int)

    def handle(self, *args, **options):
        if options.get("delivery_id"):
            try:
                delivery = WebhookDelivery.objects.get(pk=options["delivery_id"])
            except WebhookDelivery.DoesNotExist as exc:
                raise CommandError("Webhook delivery not found.") from exc
            result = send_webhook_delivery(
                delivery,
                max_attempts=options.get("max_attempts"),
                timeout_seconds=options.get("timeout"),
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Delivery {result.id}: status={result.status}, attempts={result.attempt_count}, response={result.response_status}"
                )
            )
            return

        results = send_due_webhook_deliveries(
            limit=options["limit"],
            max_attempts=options.get("max_attempts"),
            timeout_seconds=options.get("timeout"),
        )
        sent = sum(1 for delivery in results if delivery.status == WebhookDelivery.Status.SENT)
        failed = sum(1 for delivery in results if delivery.status == WebhookDelivery.Status.FAILED)
        pending = sum(1 for delivery in results if delivery.status == WebhookDelivery.Status.PENDING)
        self.stdout.write(
            self.style.SUCCESS(
                f"Webhook delivery run complete: processed={len(results)}, sent={sent}, failed={failed}, pending={pending}"
            )
        )
