import logging

from django.contrib.auth import get_user_model
from django.db import models

from .app_settings import app_settings


User = get_user_model()


LOG_LEVELS = (
    (logging.NOTSET, "Not Set"),
    (logging.INFO, "Info"),
    (logging.WARNING, "Warning"),
    (logging.DEBUG, "Debug"),
    (logging.ERROR, "Error"),
    (logging.FATAL, "Fatal"),
    (logging.CRITICAL, "Critical"),
)


class RequestLog(models.Model):
    cid = models.CharField(max_length=255, blank=True, db_index=True, default="")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_index=True)
    username_persisted = models.CharField(max_length=255, blank=True)
    requested_at = models.DateTimeField(db_index=True)
    response_ms = models.PositiveIntegerField(default=0)
    host = models.CharField(max_length=255, db_index=True)
    url = models.URLField()
    path = models.CharField(max_length=app_settings.URL_PATH_MAX_LENGTH, db_index=True)
    method = models.CharField(max_length=10)
    content_type = models.CharField(max_length=255, blank=True)
    headers = models.JSONField(null=True, default=dict)
    cookies = models.JSONField(blank=True, default=dict)
    body = models.JSONField(blank=True, default=dict)
    response = models.JSONField(blank=True, default=dict)
    query_params = models.JSONField(blank=True, default=dict)
    remote_address = models.GenericIPAddressField(null=True, blank=True)
    status_code = models.PositiveSmallIntegerField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    exception = models.TextField(blank=True)

    class Meta:
        ordering = ["-id"]
        db_table = "catch_a_log_request_log"
        verbose_name = "Request Log"
        verbose_name_plural = "Request Logs"
        indexes = [
            models.Index(fields=["user", "requested_at"]),
            models.Index(fields=["status_code", "requested_at"]),
            models.Index(fields=["url"]),
        ]

    def __str__(self):
        return f"{self.method} {self.url} - {self.status_code}"


class LoggingLog(models.Model):
    cid = models.CharField(max_length=255, blank=True, db_index=True, default="")
    created_at = models.DateTimeField(db_index=True)
    logger_name = models.CharField(max_length=255, db_index=True)
    level = models.PositiveSmallIntegerField(choices=LOG_LEVELS, db_index=True)
    msg = models.TextField(blank=True)
    args = models.TextField(blank=True)
    traceback = models.TextField(blank=True)

    class Meta:
        ordering = ["-id"]
        db_table = "catch_a_log_logging_log"
        verbose_name = "Logging Log"
        verbose_name_plural = "Logging Logs"
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["logger_name", "created_at"]),
            models.Index(fields=["level", "created_at"]),
        ]

    def __str__(self):
        return f"{self.logger_name} - {self.level}: {self.msg[:50]}"


class AuditLog(models.Model):
    cid = models.CharField(max_length=255, blank=True, db_index=True, default="")
    action = models.CharField(max_length=50, db_index=True)
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=255, db_index=True)
    changes = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-id"]
        db_table = "catch_a_log_audit_log"
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
        ]

    def __str__(self):
        return f"{self.action} on {self.model_name} #{self.object_id}"
