import logging

from django.test import TestCase

from django_catch_a_log.log_formatters import ConsoleFormatter


class ConsoleFormatterTests(TestCase):
    def test_format_without_cid(self):
        formatter = ConsoleFormatter()
        record = logging.LogRecord("test_logger", logging.INFO, "/fake/app/path.py", 10, "Hello", None, None)

        result = formatter.format(record)

        self.assertIn("[cid: ---]", result)
        self.assertIn("Hello", result)

    def test_format_with_cid(self):
        formatter = ConsoleFormatter()
        record = logging.LogRecord("test_logger", logging.INFO, "/fake/app/path.py", 10, "Hello", None, None)
        record.cid = "custom-cid"

        result = formatter.format(record)

        self.assertIn("[cid: custom-cid]", result)

    def test_format_path_exception(self):
        formatter = ConsoleFormatter()
        # Pass an invalid pathname type (e.g. None) to trigger Exception in os.path.relpath
        record = logging.LogRecord("test_logger", logging.INFO, None, 10, "Hello", None, None)

        formatter.format(record)

        self.assertTrue(hasattr(record, "clean_path"))
        self.assertIsNone(record.clean_path)

    def test_format_strips_app_prefix_from_clean_path(self):
        from django.conf import settings

        formatter = ConsoleFormatter()
        pathname = str(settings.BASE_DIR / "app" / "views.py")
        record = logging.LogRecord("test_logger", logging.INFO, pathname, 10, "Hello", None, None)

        formatter.format(record)

        self.assertEqual(record.clean_path, "views.py")

    def test_format_keeps_non_app_relative_path(self):
        from django.conf import settings

        formatter = ConsoleFormatter()
        pathname = str(settings.BASE_DIR / "django_catch_a_log" / "middlewares.py")
        record = logging.LogRecord("test_logger", logging.INFO, pathname, 10, "Hello", None, None)

        formatter.format(record)

        self.assertEqual(record.clean_path, "django_catch_a_log/middlewares.py")
