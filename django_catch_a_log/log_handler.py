import datetime as dt
import logging
import queue
import sys
import threading

from django.apps import apps
from django.conf import settings
from django.db import close_old_connections, connection, transaction

from .app_settings import app_settings
from .cid import get_cid


db_default_formatter = logging.Formatter()


class DatabaseLogHandler(logging.Handler):
    _queue = None
    _worker_thread = None
    _worker_lock = threading.Lock()

    def __init__(self):
        super().__init__()
        if not app_settings.LOG_HANDLER_SYNC:
            self._ensure_worker_started()

    @classmethod
    def _ensure_worker_started(cls):
        if cls._queue is None or cls._worker_thread is None or not cls._worker_thread.is_alive():
            with cls._worker_lock:
                if cls._queue is None:
                    maxsize = getattr(settings, "CATCH_A_LOG_QUEUE_SIZE", 10000)
                    cls._queue = queue.Queue(maxsize=maxsize)

                if cls._worker_thread is None or not cls._worker_thread.is_alive():
                    cls._worker_thread = threading.Thread(target=cls._log_worker, daemon=True, name="CatchALogWorker")
                    cls._worker_thread.start()

    def emit(self, record):
        try:
            cid = getattr(record, "cid", None) or get_cid() or ""
            cid = cid[: app_settings.CID_MAX_LENGTH]
            trace = ""
            if record.exc_info:
                trace = db_default_formatter.formatException(record.exc_info)

            msg = record.getMessage()
            created_at_aware = dt.datetime.fromtimestamp(record.created, tz=dt.UTC)

            log_data = {
                "cid": cid,
                "created_at": created_at_aware,
                "logger_name": record.name,
                "level": record.levelno,
                "msg": msg,
                "args": "",
                "traceback": trace,
            }

            if app_settings.LOG_HANDLER_SYNC:
                DatabaseLogHandler._persist_batch([log_data])
                return

            DatabaseLogHandler._queue.put(log_data, block=False)

        except queue.Full:
            pass
        except Exception:
            self.handleError(record)

    @classmethod
    def _log_worker(cls):
        batch_size = getattr(settings, "CATCH_A_LOG_BATCH_SIZE", 100)

        while True:
            data = cls._queue.get()

            if data is None:
                cls._queue.task_done()
                break

            batch = [data]

            try:
                while len(batch) < batch_size:
                    data = cls._queue.get_nowait()
                    if data is None:
                        cls._queue.put_nowait(None)
                        break
                    batch.append(data)
            except queue.Empty:
                pass

            close_old_connections()
            cls._persist_batch(batch)

            for _ in batch:
                cls._queue.task_done()

        # Thread exit, close DB connection
        connection.close()

    @classmethod
    def _persist_batch(cls, batch):
        try:
            LoggingLog = apps.get_model("django_catch_a_log.LoggingLog")
            with transaction.atomic():
                LoggingLog.objects.bulk_create([LoggingLog(**item) for item in batch])
        except Exception as e:
            sys.stderr.write(f"CatchALog DB insert failed: {e}\n")
        finally:
            connection.close()

    def close(self):
        """
        Called by the logging system during shutdown.
        Flushes the queue to ensure no logs are lost.
        """
        with DatabaseLogHandler._worker_lock:
            if DatabaseLogHandler._worker_thread and DatabaseLogHandler._worker_thread.is_alive():
                DatabaseLogHandler._queue.put(None)
                DatabaseLogHandler._worker_thread.join(timeout=5.0)
        super().close()
