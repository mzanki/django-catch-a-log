from .app_settings import app_settings
from .cid import generate_new_cid, reset_cid, set_cid
from .request_logger import RequestLogger


class PersistRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not app_settings.ENABLED:
            return self.get_response(request)

        req_logger = RequestLogger(request)

        if req_logger.is_static_or_media_request() or req_logger.skip_url_regex() or req_logger.skip_method():
            return self.get_response(request)

        req_logger.prepare_log()

        response = None
        exception = None
        try:
            response = self.get_response(request)
        except Exception as e:
            exception = e
            raise
        finally:
            should_log = True

            if app_settings.LOG_HTTP_ONLY_ERRORS:
                status_code = response.status_code if response else 500
                if status_code < 400 and exception is None:
                    should_log = False

            if should_log:
                req_logger.persist_log(response, exception)

        return response

    def process_exception(self, request, exception):
        """
        Django calls this when a view raises an exception.
        We don't save here anymore to avoid duplicate saves;
        we let the __call__ finally block handle the persistence.
        """
        return None


class CorrelationIdMiddleware:
    """
    Middleware to set a correlation ID for each request.
    Must be the first middleware to ensure CID is available for all logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        meta_key = f"HTTP_{app_settings.CORRELATION_ID_META_KEY.upper().replace('-', '_')}"
        cid = request.META.get(meta_key) or generate_new_cid()
        cid = cid[: app_settings.CID_MAX_LENGTH]

        request.correlation_id = cid
        request.META[meta_key] = cid

        token = set_cid(cid)
        try:
            response = self.get_response(request)
        finally:
            reset_cid(token)

        response[app_settings.CORRELATION_ID_META_KEY] = cid
        return response
