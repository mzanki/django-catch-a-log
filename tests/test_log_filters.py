import logging
from unittest.mock import patch

from django.test import TestCase

from django_catch_a_log.log_filters import CidFilter


class CidFilterTests(TestCase):
    @patch("django_catch_a_log.log_filters.get_cid")
    def test_filter_adds_cid(self, mock_get_cid):
        mock_get_cid.return_value = "mocked-cid-123"
        record = logging.LogRecord("test", logging.INFO, "path", 1, "msg", None, None)
        f = CidFilter()

        result = f.filter(record)

        self.assertTrue(result)
        self.assertEqual(record.cid, "mocked-cid-123")

    @patch("django_catch_a_log.log_filters.get_cid")
    def test_filter_adds_fallback_cid(self, mock_get_cid):
        mock_get_cid.return_value = None
        record = logging.LogRecord("test", logging.INFO, "path", 1, "msg", None, None)
        f = CidFilter()

        result = f.filter(record)

        self.assertTrue(result)
        self.assertEqual(record.cid, "---")
