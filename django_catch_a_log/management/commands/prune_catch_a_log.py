from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from django_catch_a_log.models import AuditLog, LoggingLog, RequestLog


TARGETS = {
    "request": RequestLog,
    "logging": LoggingLog,
    "audit": AuditLog,
}


class Command(BaseCommand):
    help = "Delete catch-a-log rows older than --days. Use --dry-run to preview."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            required=True,
            help="Remove rows whose created_at is older than N days.",
        )
        parser.add_argument(
            "--target",
            choices=[*TARGETS.keys(), "all"],
            default="all",
            help="Which log table(s) to prune. Defaults to all.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count rows that would be deleted without deleting.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=5000,
            help="Number of rows to delete per batch to avoid long locks.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days <= 0:
            raise CommandError("--days must be a positive integer")

        cutoff = timezone.now() - timedelta(days=days)
        target = options["target"]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        targets = list(TARGETS.items()) if target == "all" else [(target, TARGETS[target])]

        for name, model in targets:
            qs = model.objects.filter(created_at__lt=cutoff)
            total = qs.count()

            if dry_run:
                self.stdout.write(f"[dry-run] {name}: would delete {total} rows older than {cutoff.isoformat()}")
                continue

            if total == 0:
                self.stdout.write(f"{name}: nothing to delete")
                continue

            deleted = 0
            while True:
                pks = list(qs.values_list("pk", flat=True)[:batch_size])
                if not pks:
                    break
                count, _ = model.objects.filter(pk__in=pks).delete()
                deleted += count
                self.stdout.write(f"{name}: deleted {deleted}/{total}", ending="\r")
                self.stdout.flush()

            self.stdout.write(self.style.SUCCESS(f"{name}: deleted {deleted} rows"))
