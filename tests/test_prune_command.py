from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from django_catch_a_log.models import AuditLog, LoggingLog, RequestLog


class PruneCommandTests(TestCase):
    def setUp(self):
        now = timezone.now()
        old = now - timedelta(days=40)
        recent = now - timedelta(days=5)

        # created_at is auto_now_add on RequestLog/AuditLog, so we set and save,
        # then bump created_at via update() to simulate old rows.
        self.old_request = RequestLog.objects.create(
            requested_at=old, host="h", url="http://h/", path="/", method="GET", status_code=200
        )
        RequestLog.objects.filter(pk=self.old_request.pk).update(created_at=old)

        self.recent_request = RequestLog.objects.create(
            requested_at=recent, host="h", url="http://h/", path="/", method="GET", status_code=200
        )
        RequestLog.objects.filter(pk=self.recent_request.pk).update(created_at=recent)

        self.old_audit = AuditLog.objects.create(action="CREATE", model_name="m", object_id="1", changes={})
        AuditLog.objects.filter(pk=self.old_audit.pk).update(created_at=old)

        self.old_logging = LoggingLog.objects.create(created_at=old, logger_name="test", level=20, msg="old")
        self.recent_logging = LoggingLog.objects.create(created_at=recent, logger_name="test", level=20, msg="recent")

    def test_requires_positive_days(self):
        with self.assertRaises(CommandError):
            call_command("prune_catch_a_log", "--days=0")

    def test_dry_run_does_not_delete(self):
        out = StringIO()
        call_command("prune_catch_a_log", "--days=30", "--dry-run", stdout=out)
        self.assertEqual(RequestLog.objects.count(), 2)
        self.assertEqual(LoggingLog.objects.count(), 2)
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertIn("dry-run", out.getvalue())

    def test_prune_only_requests(self):
        call_command("prune_catch_a_log", "--days=30", "--target=request", stdout=StringIO())
        self.assertEqual(RequestLog.objects.count(), 1)
        self.assertEqual(RequestLog.objects.first().pk, self.recent_request.pk)
        # Other models untouched.
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertEqual(LoggingLog.objects.count(), 2)

    def test_prune_all(self):
        call_command("prune_catch_a_log", "--days=30", stdout=StringIO())
        self.assertEqual(RequestLog.objects.count(), 1)
        self.assertEqual(LoggingLog.objects.count(), 1)
        self.assertEqual(AuditLog.objects.count(), 0)
