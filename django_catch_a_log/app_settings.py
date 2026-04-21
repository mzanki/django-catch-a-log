from django.conf import settings


class AppSettings:
    default_sensitive_keys = [
        "password",
        "token",
        "access",
        "refresh",
        "sessionid",
        "authorization",
        "bearer",
        "csrftoken",
        "csrfmiddlewaretoken",
    ]

    def __init__(self, prefix):
        self.prefix = prefix

    def _setting(self, name, default):
        settings_name = f"{self.prefix}{name}"
        return getattr(settings, settings_name, default)

    @property
    def ENABLED(self) -> bool:
        return self._setting("ENABLED", True)

    @property
    def LOG_HTTP_ONLY_ERRORS(self):
        return self._setting("LOG_HTTP_ONLY_ERRORS", True)

    @property
    def URL_PATH_MAX_LENGTH(self):
        return self._setting("URL_PATH_MAX_LENGTH", 1000)

    @property
    def SENSITIVE_KEYS(self):
        return self._setting("SENSITIVE_KEYS", self.default_sensitive_keys)

    @property
    def SLOW_REQUEST_THRESHOLD(self):
        return self._setting("SLOW_REQUEST_THRESHOLD", 5000)

    @property
    def WHITELISTED_URLS(self):
        return self._setting("WHITELISTED_URLS", [])

    @property
    def BLACKLISTED_URLS(self):
        return self._setting("BLACKLISTED_URLS", [])

    @property
    def LOG_SELECTED_METHODS(self):
        return self._setting("LOG_SELECTED_METHODS", ["GET", "POST", "PUT", "PATCH", "DELETE"])

    @property
    def LOG_SELECTED_STATUSES(self):
        return self._setting("LOG_SELECTED_STATUSES", [])

    @property
    def CORRELATION_ID_META_KEY(self) -> str:
        return self._setting("CORRELATION_ID_META_KEY", "X_CORRELATION_ID")

    @property
    def AUDIT_LOGGING_ENABLED(self):
        return self._setting("AUDIT_LOGGING_ENABLED", True)

    @property
    def REQUEST_BODY_MAX_BYTES(self) -> int:
        return self._setting("REQUEST_BODY_MAX_BYTES", 100_000)

    @property
    def RESPONSE_BODY_MAX_BYTES(self) -> int:
        return self._setting("RESPONSE_BODY_MAX_BYTES", 100_000)

    @property
    def LOG_HANDLER_SYNC(self) -> bool:
        return self._setting("LOG_HANDLER_SYNC", False)

    @property
    def CID_MAX_LENGTH(self) -> int:
        return self._setting("CID_MAX_LENGTH", 255)


app_settings = AppSettings("CATCHALOG_")
