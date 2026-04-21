import logging
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.utils import timezone

from django_catch_a_log.admin import (
    AuditLogAdmin,
    LoggingLogAdmin,
    RequestLogAdmin,
    SlowAPIsFilter,
    custom_app_index,
    dummy_action_logs,
)
from django_catch_a_log.models import AuditLog, LoggingLog, RequestLog


class AdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.request_factory = RequestFactory()

    @patch("django_catch_a_log.admin.logger")
    def test_dummy_action_logs(self, mock_logger):
        dummy_action_logs(None, None, None)
        mock_logger.debug.assert_called_once()
        mock_logger.info.assert_called_once()
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_called_once()
        mock_logger.critical.assert_called_once()

    @patch("django_catch_a_log.admin.app_settings")
    def test_slow_apis_filter(self, mock_app_settings):
        # Setup settings and Admin instance
        mock_app_settings.SLOW_REQUEST_THRESHOLD = 1000
        admin = RequestLogAdmin(RequestLog, self.site)
        request = self.request_factory.get("/?request_performance=slow")

        # Test Filter init and lookups
        filter_instance = SlowAPIsFilter(request, {"request_performance": "slow"}, RequestLog, admin)

        lookups = filter_instance.lookups(request, admin)
        self.assertEqual(len(lookups), 2)
        self.assertEqual(lookups[0][0], "slow")
        self.assertEqual(lookups[1][0], "fast")

        # Test Filter Queryset logic
        mock_queryset = MagicMock()

        filter_instance.value = MagicMock(return_value="slow")
        filter_instance.queryset(request, mock_queryset)
        mock_queryset.filter.assert_called_with(response_ms__gte=1000)

        filter_instance.value = MagicMock(return_value="fast")
        filter_instance.queryset(request, mock_queryset)
        mock_queryset.filter.assert_called_with(response_ms__lt=1000)

    def test_request_log_admin_permissions(self):
        admin = RequestLogAdmin(RequestLog, self.site)
        request = self.request_factory.get("/")
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request))

    def test_logging_log_admin_permissions(self):
        admin = LoggingLogAdmin(LoggingLog, self.site)
        request = self.request_factory.get("/")
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request))

    def test_audit_log_admin_permissions(self):
        admin = AuditLogAdmin(AuditLog, self.site)
        request = self.request_factory.get("/")
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request))
        self.assertFalse(admin.has_delete_permission(request))

    def test_logging_log_admin_formatters(self):
        admin = LoggingLogAdmin(LoggingLog, self.site)

        # Test shorten_msg
        mock_obj = MagicMock()
        mock_obj.msg = "A" * 60
        self.assertTrue(admin.shorten_msg(mock_obj).endswith("..."))

        mock_obj.msg = "Short msg"
        self.assertEqual(admin.shorten_msg(mock_obj), "Short msg")

        # Test colored_level
        mock_obj.level = logging.INFO
        mock_obj.get_level_display.return_value = "INFO"
        self.assertIn("green", admin.colored_level(mock_obj))

        mock_obj.level = logging.WARNING
        mock_obj.get_level_display.return_value = "WARNING"
        self.assertIn("orange", admin.colored_level(mock_obj))

        mock_obj.level = logging.ERROR
        mock_obj.get_level_display.return_value = "ERROR"
        self.assertIn("red", admin.colored_level(mock_obj))

        # Test formatted_created_at
        mock_obj.created_at = timezone.now()
        formatted_date = admin.formatted_created_at(mock_obj)
        self.assertIn(str(mock_obj.created_at.year), formatted_date)

    @patch("django_catch_a_log.admin.RequestLog.objects.get")
    @patch("django_catch_a_log.admin.LoggingLog.objects.filter")
    @patch("django.contrib.admin.ModelAdmin.changeform_view")
    def test_request_log_admin_changeform_view(self, mock_super_view, mock_filter, mock_get):
        admin = RequestLogAdmin(RequestLog, self.site)
        request = self.request_factory.get("/")
        mock_obj = MagicMock()
        mock_obj.cid = "123"
        mock_get.return_value = mock_obj

        admin.changeform_view(request, "1", "", {})
        mock_filter.assert_called_once_with(cid="123")
        mock_super_view.assert_called_once()

    @patch("django_catch_a_log.admin.LoggingLog.objects.get")
    @patch("django_catch_a_log.admin.LoggingLog.objects.filter")
    @patch("django.contrib.admin.ModelAdmin.changeform_view")
    def test_logging_log_admin_changeform_view(self, mock_super_view, mock_filter, mock_get):
        admin = LoggingLogAdmin(LoggingLog, self.site)
        request = self.request_factory.get("/")
        mock_obj = MagicMock()
        mock_obj.cid = "123"
        mock_get.return_value = mock_obj

        admin.changeform_view(request, "1", "", {})
        mock_filter.assert_called_once_with(cid="123")
        mock_super_view.assert_called_once()

    @patch("django_catch_a_log.admin.original_app_index")
    @patch("django_catch_a_log.admin.RequestLog.objects")
    def test_custom_app_index(self, mock_objects, mock_original_index):
        request = self.request_factory.get("/")

        # Mock ORM method chain for dashboard queries
        mock_qs = MagicMock()
        mock_objects.annotate.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        # Return list representing mock DB row dictionaries
        mock_qs.order_by.return_value = [{"date": "2023-01-01", "total": 5, "path": "/api/", "status_code": 200}]
        mock_objects.values.return_value = mock_qs

        custom_app_index(request, "catch_a_log")

        mock_original_index.assert_called_once()
        args, kwargs = mock_original_index.call_args
        self.assertEqual(args[0], request)
        self.assertEqual(args[1], "catch_a_log")

        # Also test non-matching app label passthrough
        custom_app_index(request, "other_app")
        self.assertEqual(mock_original_index.call_count, 2)
