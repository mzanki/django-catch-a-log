import logging

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.html import format_html

from .app_settings import app_settings
from .models import AuditLog, LoggingLog, RequestLog


User = get_user_model()

logger = logging.getLogger(__name__)


def dummy_action_logs(modeladmin, request, queryset):
    logger.debug("Dummy action admin debug: %s", "arg test", extra={"var": "foo"})
    logger.info("Dummy action admin info", {"my_args": "123"}, extra={"info_key": "info_value"})
    logger.warning("Dummy action admin warning")
    logger.error("Dummy action admin error")
    logger.critical("Dummy action admin critical")


dummy_action_logs.short_description = "Perform dummy action logs"


original_app_index = admin.site.app_index


class SlowAPIsFilter(admin.SimpleListFilter):
    title = "Request Performance"
    parameter_name = "request_performance"

    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        if app_settings.SLOW_REQUEST_THRESHOLD:
            self.SLOW_REQUEST_THRESHOLD = app_settings.SLOW_REQUEST_THRESHOLD / 1000

    def lookups(self, request, model_admin):
        slow = "Slow"
        fast = "Fast"
        if app_settings.SLOW_REQUEST_THRESHOLD:
            slow += f", >={app_settings.SLOW_REQUEST_THRESHOLD}ms"
            fast += f", <{app_settings.SLOW_REQUEST_THRESHOLD}ms"

        return (
            ("slow", slow),
            ("fast", fast),
        )

    def queryset(self, request, queryset):
        if self.value() == "slow":
            return queryset.filter(response_ms__gte=app_settings.SLOW_REQUEST_THRESHOLD)
        if self.value() == "fast":
            return queryset.filter(response_ms__lt=app_settings.SLOW_REQUEST_THRESHOLD)

        return queryset


class RequestLogAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = (
        "id",
        "cid",
        "username_persisted",
        "path",
        "method",
        "status_code",
        "requested_at",
        "response_ms",
    )
    list_filter = ("method", "status_code", "requested_at")
    search_fields = ("path", "username_persisted", "cid")
    change_form_template = "catch_a_log/change_form.html"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if app_settings.SLOW_REQUEST_THRESHOLD:
            self.list_filter = self.list_filter + (SlowAPIsFilter,)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id, form_url, extra_context):
        obj = RequestLog.objects.get(id=object_id)
        extra_context = {"logging_logs": LoggingLog.objects.filter(cid=obj.cid).order_by("id")}
        return super().changeform_view(request, object_id, form_url, extra_context)


class LoggingLogAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = ("id", "colored_level", "cid", "logger_name", "formatted_created_at", "shorten_msg")
    list_filter = ("level", "logger_name", "created_at")
    search_fields = ("logger_name", "msg", "cid")
    readonly_fields = ("formatted_created_at",)
    exclude = ("created_at",)
    change_form_template = "catch_a_log/logger_change_form.html"
    actions = [dummy_action_logs]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def shorten_msg(self, obj):
        return f"{obj.msg[:50] + '...' if len(obj.msg) > 50 else obj.msg}"

    shorten_msg.short_description = "Message"

    def formatted_created_at(self, obj):
        local_time = timezone.localtime(obj.created_at)
        return f"{local_time.strftime('%Y-%m-%d %H:%M:%S')}.{local_time.microsecond:06d}"

    formatted_created_at.short_description = "Created at"

    def colored_level(self, instance):
        color = ""
        if instance.level == logging.INFO:
            color = "green"
        elif instance.level == logging.WARNING:
            color = "orange"
        elif instance.level in (logging.ERROR, logging.FATAL, logging.CRITICAL):
            color = "red"

        return format_html(
            '<span style="color: {color};">{level}</span>', color=color, level=instance.get_level_display().upper()
        )

    colored_level.short_description = "Level"

    def changeform_view(self, request, object_id, form_url, extra_context):
        obj = LoggingLog.objects.get(id=object_id)
        extra_context = {"related_logs": LoggingLog.objects.filter(cid=obj.cid).order_by("-id")}
        return super().changeform_view(request, object_id, form_url, extra_context)


class AuditLogAdmin(admin.ModelAdmin):
    list_per_page = 20
    list_display = ("id", "created_at", "cid", "action", "model_name", "object_id")
    list_filter = ("action", "model_name", "created_at")
    search_fields = ("cid", "object_id", "model_name")
    readonly_fields = ("cid", "action", "model_name", "object_id", "changes", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AuditableModelAdmin(admin.ModelAdmin):
    """
    Apply this mixin to any ModelAdmin to inject the 'View Audit Logs' button
    into its change form.
    """

    if app_settings.AUDIT_LOGGING_ENABLED:
        change_form_template = "catch_a_log/audit_change_form.html"


def custom_app_index(request, app_label, extra_context=None):
    if app_label == "catch_a_log":
        extra_context = extra_context or {}

        error_trend = (
            RequestLog.objects.annotate(date=TruncDate("requested_at"))
            .values("date")
            .annotate(total=Count("id"))
            .order_by("date")
        )

        top_paths = RequestLog.objects.values("path").annotate(total=Count("id")).order_by("-total")[:10]

        status_codes = RequestLog.objects.values("status_code").annotate(total=Count("id")).order_by("status_code")

        extra_context.update(
            error_trend=error_trend,
            top_paths_keys=list(item["path"] for item in top_paths),
            top_paths_values=list(item["total"] for item in top_paths),
            status_code_keys=list(item["status_code"] for item in status_codes),
            status_code_values=list(item["total"] for item in status_codes),
        )
    return original_app_index(request, app_label, extra_context)


if app_settings.ENABLED:
    admin.site.app_index = custom_app_index

    admin.site.register(RequestLog, RequestLogAdmin)
    admin.site.register(LoggingLog, LoggingLogAdmin)
    if app_settings.AUDIT_LOGGING_ENABLED:
        admin.site.register(AuditLog, AuditLogAdmin)
