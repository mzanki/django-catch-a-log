import logging
import queue
import sys
from unittest.mock import MagicMock, patch

from django.test import TestCase

from django_catch_a_log.log_handler import DatabaseLogHandler


class DatabaseLogHandlerTests(TestCase):
    def setUp(self):
        # Prevent actual thread start during basic unit tests
        self.thread_patcher = patch("threading.Thread")
        self.mock_thread = self.thread_patcher.start()

    def tearDown(self):
        self.thread_patcher.stop()

    def test_handler_init_starts_worker(self):
        handler = DatabaseLogHandler()
        self.assertIsNotNone(handler._queue)

    @patch("django_catch_a_log.log_handler.get_cid")
    def test_emit_puts_in_queue(self, mock_get_cid):
        mock_get_cid.return_value = "queue-cid-1"
        handler = DatabaseLogHandler()

        record = logging.LogRecord("test_logger", logging.INFO, "path.py", 10, "DB Msg", None, None)

        # Clear queue for test
        while not handler._queue.empty():
            handler._queue.get()

        handler.emit(record)

        self.assertFalse(handler._queue.empty())
        item = handler._queue.get()
        self.assertEqual(item["msg"], "DB Msg")
        self.assertEqual(item["cid"], "queue-cid-1")

    def test_emit_with_exception(self):
        handler = DatabaseLogHandler()
        while not handler._queue.empty():
            handler._queue.get()
        try:
            1 / 0  # noqa: B018
        except Exception:
            record = logging.LogRecord("test_logger", logging.ERROR, "path.py", 10, "Error", None, sys.exc_info())
        handler.emit(record)
        item = handler._queue.get()
        self.assertIn("ZeroDivisionError", item["traceback"])

    def test_emit_queue_full(self):
        handler = DatabaseLogHandler()
        with patch.object(handler._queue, "put", side_effect=queue.Full):
            record = logging.LogRecord("test_logger", logging.INFO, "path.py", 10, "DB Msg", None, None)
            handler.emit(record)  # Should pass silently

    @patch("logging.Handler.handleError")
    def test_emit_general_exception(self, mock_handle_error):
        handler = DatabaseLogHandler()
        with patch.object(handler._queue, "put", side_effect=ValueError("Test")):
            record = logging.LogRecord("test_logger", logging.INFO, "path.py", 10, "DB Msg", None, None)
            handler.emit(record)
            mock_handle_error.assert_called_once_with(record)

    @patch("django_catch_a_log.log_handler.apps.get_model")
    @patch("django_catch_a_log.log_handler.transaction.atomic")
    @patch("django_catch_a_log.log_handler.connection.close")
    def test_persist_batch_success(self, mock_close, mock_atomic, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        batch = [{"msg": "test1"}]
        DatabaseLogHandler._persist_batch(batch)
        mock_model.objects.bulk_create.assert_called_once()
        mock_close.assert_called_once()

    @patch("django_catch_a_log.log_handler.sys.stderr.write")
    @patch("django_catch_a_log.log_handler.apps.get_model", side_effect=Exception("DB fail"))
    @patch("django_catch_a_log.log_handler.connection.close")
    def test_persist_batch_exception(self, mock_close, mock_get_model, mock_stderr_write):
        DatabaseLogHandler._persist_batch([{"msg": "test"}])
        mock_stderr_write.assert_called_once()
        mock_close.assert_called_once()

    @patch("django_catch_a_log.log_handler.DatabaseLogHandler._persist_batch")
    @patch("django_catch_a_log.log_handler.close_old_connections")
    @patch("django_catch_a_log.log_handler.connection.close")
    def test_log_worker_loop(self, mock_conn_close, mock_close_old, mock_persist):
        handler = DatabaseLogHandler()
        while not handler._queue.empty():
            handler._queue.get()
        handler._queue.put({"msg": "test1"})
        handler._queue.put({"msg": "test2"})
        handler._queue.put(None)  # Sentinel to break loop

        DatabaseLogHandler._log_worker()

        mock_persist.assert_called_once()
        passed_batch = mock_persist.call_args[0][0]
        self.assertEqual(len(passed_batch), 2)
        mock_conn_close.assert_called_once()

    def test_close(self):
        handler = DatabaseLogHandler()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        DatabaseLogHandler._worker_thread = mock_thread

        handler.close()

        mock_thread.join.assert_called_once_with(timeout=5.0)
        while not handler._queue.empty():
            handler._queue.get()

    @patch("django_catch_a_log.log_handler.app_settings")
    @patch("django_catch_a_log.log_handler.DatabaseLogHandler._persist_batch")
    def test_emit_sync_mode_writes_directly(self, mock_persist, mock_settings):
        mock_settings.LOG_HANDLER_SYNC = True
        mock_settings.CID_MAX_LENGTH = 255
        handler = DatabaseLogHandler()

        record = logging.LogRecord("test_logger", logging.INFO, "path.py", 10, "Sync msg", None, None)
        handler.emit(record)

        mock_persist.assert_called_once()
        batch = mock_persist.call_args[0][0]
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["msg"], "Sync msg")

    @patch("django_catch_a_log.log_handler.app_settings")
    def test_emit_truncates_long_cid(self, mock_settings):
        mock_settings.LOG_HANDLER_SYNC = False
        mock_settings.CID_MAX_LENGTH = 8
        handler = DatabaseLogHandler()
        while not handler._queue.empty():
            handler._queue.get()
        record = logging.LogRecord("test_logger", logging.INFO, "path.py", 10, "m", None, None)
        record.cid = "x" * 500
        handler.emit(record)
        item = handler._queue.get()
        self.assertEqual(len(item["cid"]), 8)
