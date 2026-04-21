import copy
import json
import logging
import re
import traceback

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .app_settings import app_settings
from .cid import get_cid
from .models import RequestLog


logger = logging.getLogger(__name__)


class RequestLogger:
    def __init__(self, request: HttpRequest):
        self.request = request
        self.log_instance: RequestLog | None = None
        self.response = None
        self.start_time = timezone.now()

    def is_static_or_media_request(self):
        path = self.request.path
        static_url = getattr(settings, "STATIC_URL", None)
        media_url = getattr(settings, "MEDIA_URL", None)

        if static_url and static_url != "/" and path.startswith(static_url):
            return True

        return bool(media_url and media_url != "/" and path.startswith(media_url))

    def skip_url_regex(self):
        path = self.request.path
        if app_settings.WHITELISTED_URLS:
            return all(not re.match(r"^" + url, path) for url in app_settings.WHITELISTED_URLS)

        return any(re.match(r"^" + url, path) for url in app_settings.BLACKLISTED_URLS)

    def skip_method(self):
        return self.request.method not in app_settings.LOG_SELECTED_METHODS

    def _get_user(self):
        user = getattr(self.request, "user", None)
        if user and not user.is_anonymous:
            return user
        return None

    def _mask_sensitive_keys(self, data):
        """Recursively masks keys defined in settings without mutating original request data."""
        if not data:
            return data

        if isinstance(data, (dict, list)):
            data = copy.deepcopy(data)

        if isinstance(data, dict):
            for key, value in data.items():
                if any(sk.lower() in key.lower() for sk in app_settings.SENSITIVE_KEYS):
                    data[key] = "********"
                elif isinstance(value, (dict, list)):
                    data[key] = self._mask_sensitive_keys(value)
        elif isinstance(data, list):
            data = [self._mask_sensitive_keys(item) if isinstance(item, (dict, list)) else item for item in data]
        return data

    def _get_headers(self):
        headers = {
            re.sub("^HTTP_", "", k).replace("_", "-").title(): v
            for k, v in self.request.META.items()
            if k.startswith("HTTP_")
        }

        if "CONTENT_TYPE" in self.request.META:
            headers["Content-Type"] = self.request.META["CONTENT_TYPE"]

        headers.pop("Cookie", None)
        headers.pop("COOKIE", None)

        return headers

    def _get_cookies(self):
        """Returns Django's safely parsed cookie dictionary."""
        return dict(self.request.COOKIES)

    def _get_remote_address(self):
        x_forwarded_for = self.request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return self.request.META.get("REMOTE_ADDR", "")

    def _sanitize_body(self):
        """
        SAFE body reading.
        Reads the body only after ensuring Django has cached it or
        parsing it based on Content-Type.
        """
        if self.request.method == "GET":
            return {}

        content_type = self.request.content_type or ""
        max_bytes = app_settings.REQUEST_BODY_MAX_BYTES

        try:
            raw = self.request.body
            if max_bytes and len(raw) > max_bytes:
                return {"_omitted": "Request body exceeds size cap", "size_bytes": len(raw), "max_bytes": max_bytes}

            if "application/json" in content_type:
                return json.loads(raw.decode("utf-8"))

            if "application/x-www-form-urlencoded" in content_type:
                return dict(self.request.POST)

            if "multipart/form-data" in content_type:
                return {"_info": "Multipart data captured", "fields": list(self.request.POST.keys())}

            return {"_raw_text": raw.decode("utf-8", errors="ignore")}
        except Exception as e:
            # Body may be unavailable (stream consumed, too large, binary).
            logger.debug("Failed to sanitize request body: %s", e)
            return {}

    def _sanitize_response_body(self):
        if not self.response:
            return {}

        content_type = self.response.get("Content-Type", "")
        max_bytes = app_settings.RESPONSE_BODY_MAX_BYTES

        try:
            content = self.response.content
            if max_bytes and len(content) > max_bytes:
                return {
                    "_omitted": "Response body exceeds size cap",
                    "size_bytes": len(content),
                    "max_bytes": max_bytes,
                }

            if "application/json" in content_type:
                return json.loads(content.decode("utf-8"))

            if "text/html" in content_type:
                return {"_omitted": "HTML Error Page", "note": "See Traceback or Status Code"}

            if "text/plain" in content_type:
                return {"_raw_text": content.decode("utf-8", errors="ignore")}

            return {"_omitted": f"{content_type} Response Omitted"}

        except Exception as e:
            logger.debug("Failed to sanitize response body: %s", e)
            return {"_error": "Binary or unparseable response"}

    def prepare_log(self):
        """Initializes the log object in memory with request metadata."""
        if not app_settings.ENABLED:
            return

        self.log_instance = RequestLog(
            cid=get_cid() or "",
            requested_at=self.start_time,
            host=self.request.get_host(),
            url=self.request.build_absolute_uri(),
            path=self.request.path,
            method=self.request.method,
            content_type=self.request.content_type or "",
            remote_address=self._get_remote_address(),
        )

    def _get_query_params(self):
        """Extracts query parameters regardless of the HTTP method."""
        return dict(self.request.GET)

    def persist_log(self, response: HttpResponse | None, exception: Exception | None = None):
        """Finalizes and saves the log. Safe to call multiple times."""
        if not app_settings.ENABLED or not self.log_instance:
            return

        self.response = response
        status_code = response.status_code if response else 500

        if app_settings.LOG_SELECTED_STATUSES and status_code not in app_settings.LOG_SELECTED_STATUSES:
            return

        user = self._get_user()

        self.log_instance.user = user
        self.log_instance.username_persisted = user.get_username() if user else "Anonymous"
        self.log_instance.response_ms = int((timezone.now() - self.start_time).total_seconds() * 1000)
        self.log_instance.status_code = status_code

        # Single deepcopy pass over all payloads instead of one per field.
        masked = self._mask_sensitive_keys(
            {
                "cookies": self._get_cookies(),
                "query_params": self._get_query_params(),
                "headers": self._get_headers(),
                "body": self._sanitize_body(),
                "response": self._sanitize_response_body(),
            }
        )
        self.log_instance.cookies = masked["cookies"]
        self.log_instance.query_params = masked["query_params"]
        self.log_instance.headers = masked["headers"]
        self.log_instance.body = masked["body"]
        self.log_instance.response = masked["response"]

        if exception:
            self.log_instance.exception = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            )

        try:
            self.log_instance.save()
        except Exception as e:
            logger.error(f"Failed to save request log: {e}")
