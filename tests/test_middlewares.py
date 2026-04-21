from django.http import HttpResponse, HttpResponseNotFound
from django.test import RequestFactory, TestCase, override_settings

from django_catch_a_log.cid import get_cid
from django_catch_a_log.middlewares import CorrelationIdMiddleware, PersistRequestMiddleware
from django_catch_a_log.models import RequestLog


class CorrelationIdMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.seen_cid = None

        def get_response(request):
            self.seen_cid = get_cid()
            return HttpResponse("OK", status=200)

        self.get_response = get_response
        self.middleware = CorrelationIdMiddleware(self.get_response)

    def test_generates_new_cid_if_none_provided(self):
        request = self.factory.get("/test-url/")

        response = self.middleware(request)

        self.assertTrue(hasattr(request, "correlation_id"))
        self.assertIsNotNone(request.correlation_id)

        # CID is set during view execution, then reset to prevent leaking between requests.
        self.assertEqual(self.seen_cid, request.correlation_id)
        self.assertIsNone(get_cid())

        self.assertEqual(response["X_CORRELATION_ID"], request.correlation_id)

    @override_settings(CATCHALOG_CORRELATION_ID_META_KEY="X-Custom-ID")
    def test_uses_existing_cid_from_headers(self):
        request = self.factory.get("/test-url/", HTTP_X_CUSTOM_ID="frontend-12345")

        middleware = CorrelationIdMiddleware(self.get_response)
        response = middleware(request)

        self.assertEqual(request.correlation_id, "frontend-12345")
        self.assertEqual(self.seen_cid, "frontend-12345")
        self.assertIsNone(get_cid())
        self.assertEqual(response["X-Custom-ID"], "frontend-12345")

    def test_cid_isolated_between_consecutive_requests(self):
        """Two back-to-back requests on the same thread must not share or leak CID state."""
        seen = []

        def view(request):
            seen.append(get_cid())
            return HttpResponse("OK")

        mw = CorrelationIdMiddleware(view)
        mw(self.factory.get("/a/"))
        mw(self.factory.get("/b/"))

        self.assertEqual(len(seen), 2)
        self.assertIsNotNone(seen[0])
        self.assertIsNotNone(seen[1])
        self.assertNotEqual(seen[0], seen[1])
        self.assertIsNone(get_cid())

    def test_cid_reset_even_when_view_raises(self):
        def exploding_view(request):
            raise ValueError("boom")

        mw = CorrelationIdMiddleware(exploding_view)
        with self.assertRaises(ValueError):
            mw(self.factory.get("/crash/"))
        self.assertIsNone(get_cid())

    @override_settings(CATCHALOG_CID_MAX_LENGTH=10)
    def test_incoming_cid_is_truncated_to_max_length(self):
        request = self.factory.get("/", HTTP_X_CORRELATION_ID="a" * 500)
        middleware = CorrelationIdMiddleware(self.get_response)
        middleware(request)
        self.assertEqual(len(request.correlation_id), 10)


class PersistRequestMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def get_middleware_chain(self, view):
        persist_mw = PersistRequestMiddleware(view)
        return CorrelationIdMiddleware(persist_mw)

    def test_logging_by_status_code(self):
        scenarios = [
            (200, HttpResponse, 0),
            (404, HttpResponseNotFound, 1),
            (403, HttpResponse, 1),
        ]

        for status, response_class, expected_count in scenarios:
            with self.subTest(status_code=status):
                RequestLog.objects.all().delete()

                def view(r, res_cls=response_class, st=status):
                    return res_cls(status=st)

                chain = self.get_middleware_chain(view)

                request = self.factory.get("/test-path/")
                chain(request)

                self.assertEqual(
                    RequestLog.objects.count(),
                    expected_count,
                    f"Expected {expected_count} logs for status {status}, but found {RequestLog.objects.count()}",
                )

    def test_exception_is_always_logged(self):
        def exploding_view(request):
            raise ValueError("Boom!")

        chain = self.get_middleware_chain(exploding_view)
        request = self.factory.get("/crash/")

        with self.assertRaises(ValueError):
            chain(request)

        self.assertEqual(RequestLog.objects.count(), 1)
        log = RequestLog.objects.first()
        self.assertEqual(log.status_code, 500)

    @override_settings(CATCHALOG_LOG_HTTP_ONLY_ERRORS=False)
    def test_force_log_all_setting(self):

        def view(r):
            return HttpResponse("I should be logged now", status=200)

        chain = self.get_middleware_chain(view)

        request = self.factory.get("/logged-success/")
        chain(request)

        self.assertEqual(RequestLog.objects.count(), 1)

    @override_settings(CATCHALOG_ENABLED=False)
    def test_disabled_setting_skips_persistence(self):
        def view(r):
            return HttpResponse(status=500)

        chain = self.get_middleware_chain(view)
        chain(self.factory.get("/x/"))
        self.assertEqual(RequestLog.objects.count(), 0)

    @override_settings(STATIC_URL="/static/", CATCHALOG_LOG_HTTP_ONLY_ERRORS=False)
    def test_static_request_skipped(self):
        def view(r):
            return HttpResponse("css", status=200)

        chain = self.get_middleware_chain(view)
        chain(self.factory.get("/static/main.css"))
        self.assertEqual(RequestLog.objects.count(), 0)

    @override_settings(CATCHALOG_LOG_SELECTED_METHODS=["POST"], CATCHALOG_LOG_HTTP_ONLY_ERRORS=False)
    def test_method_not_in_allowlist_skipped(self):
        def view(r):
            return HttpResponse("ok", status=200)

        chain = self.get_middleware_chain(view)
        chain(self.factory.get("/x/"))
        self.assertEqual(RequestLog.objects.count(), 0)

    @override_settings(CATCHALOG_BLACKLISTED_URLS=[r"/healthz"], CATCHALOG_LOG_HTTP_ONLY_ERRORS=False)
    def test_blacklisted_url_skipped(self):
        def view(r):
            return HttpResponse("ok", status=200)

        chain = self.get_middleware_chain(view)
        chain(self.factory.get("/healthz/"))
        self.assertEqual(RequestLog.objects.count(), 0)
