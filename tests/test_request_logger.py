import json
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from django_catch_a_log.models import RequestLog
from django_catch_a_log.request_logger import RequestLogger


class RequestLoggerTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(STATIC_URL="/static/", MEDIA_URL="/media/")
    def test_is_static_or_media_request(self):
        scenarios = [
            ("/static/css/style.css", True),
            ("/media/img/logo.png", True),
            ("/api/data/", False),
            ("/", False),
        ]
        for path, expected in scenarios:
            with self.subTest(path=path):
                request = self.factory.get(path)
                logger = RequestLogger(request)
                self.assertEqual(logger.is_static_or_media_request(), expected)

    def test_skip_url_regex_blacklist(self):
        scenarios = [
            ("/api/secret/", True),
            ("/api/public/", False),
        ]
        for path, expected in scenarios:
            with self.subTest(path=path):
                request = self.factory.get(path)
                with override_settings(CATCHALOG_BLACKLISTED_URLS=[r"/api/secret/"], CATCHALOG_WHITELISTED_URLS=[]):
                    logger = RequestLogger(request)
                    self.assertEqual(logger.skip_url_regex(), expected)

    def test_skip_url_regex_whitelist(self):
        scenarios = [
            ("/api/public/", False),
            ("/api/secret/", True),
        ]
        for path, expected in scenarios:
            with self.subTest(path=path):
                request = self.factory.get(path)
                with override_settings(CATCHALOG_WHITELISTED_URLS=[r"/api/public/"]):
                    logger = RequestLogger(request)
                    self.assertEqual(logger.skip_url_regex(), expected)

    def test_skip_method(self):
        scenarios = [
            ("GET", ["POST", "PUT"], True),
            ("POST", ["POST", "PUT"], False),
        ]
        for method, allowed_methods, expected in scenarios:
            with self.subTest(method=method):
                request = self.factory.generic(method, "/")
                with override_settings(CATCHALOG_LOG_SELECTED_METHODS=allowed_methods):
                    logger = RequestLogger(request)
                    self.assertEqual(logger.skip_method(), expected)

    @override_settings(CATCHALOG_SENSITIVE_KEYS=["password", "token"])
    def test_mask_sensitive_keys(self):
        request = self.factory.get("/")
        logger = RequestLogger(request)

        data = {
            "public": "safe",
            "password": "secret_pass",
            "nested": {
                "api_token": "12345",
                "normal": "value",
            },
            "list_data": [
                {"token": "abc"},
                "plain_string",
            ],
        }

        masked = logger._mask_sensitive_keys(data)

        self.assertEqual(masked["public"], "safe")
        self.assertEqual(masked["password"], "********")
        self.assertEqual(masked["nested"]["api_token"], "********")
        self.assertEqual(masked["nested"]["normal"], "value")
        self.assertEqual(masked["list_data"][0]["token"], "********")
        self.assertEqual(masked["list_data"][1], "plain_string")
        self.assertEqual(data["password"], "secret_pass")

    def test_get_remote_address(self):
        scenarios = [
            ({"HTTP_X_FORWARDED_FOR": "192.168.1.1, 10.0.0.1"}, "192.168.1.1"),
            ({"REMOTE_ADDR": "10.0.0.1"}, "10.0.0.1"),
            ({"REMOTE_ADDR": ""}, ""),
        ]
        for meta, expected in scenarios:
            with self.subTest(meta=meta):
                request = self.factory.get("/", **meta)
                logger = RequestLogger(request)
                self.assertEqual(logger._get_remote_address(), expected)

    def test_get_headers(self):
        request = self.factory.get(
            "/",
            HTTP_USER_AGENT="test-agent",
            HTTP_COOKIE="sessionid=123",
            CONTENT_TYPE="application/json",
        )
        logger = RequestLogger(request)
        headers = logger._get_headers()

        self.assertEqual(headers.get("User-Agent"), "test-agent")
        self.assertEqual(headers.get("Content-Type"), "application/json")
        self.assertNotIn("Cookie", headers)

    def test_sanitize_body(self):
        scenarios = [
            ("GET", "", "", {}),
            ("POST", "application/json", '{"key": "value"}', {"key": "value"}),
            (
                "POST",
                "application/x-www-form-urlencoded",
                "key=value&key2=val2",
                {"key": ["value"], "key2": ["val2"]},
            ),
            (
                "POST",
                "text/plain",
                "just some text",
                {"_raw_text": "just some text"},
            ),
        ]
        for method, content_type, body, expected in scenarios:
            with self.subTest(method=method, content_type=content_type):
                if method == "GET":
                    request = self.factory.get("/")
                else:
                    request = self.factory.generic(method, "/", body, content_type=content_type)
                logger = RequestLogger(request)
                self.assertEqual(logger._sanitize_body(), expected)

    def test_sanitize_response_body(self):
        scenarios = [
            ("application/json", b'{"res": "ok"}', {"res": "ok"}),
            (
                "text/html",
                b"<html></html>",
                {"_omitted": "HTML Error Page", "note": "See Traceback or Status Code"},
            ),
            ("text/plain", b"plain response", {"_raw_text": "plain response"}),
            (
                "application/pdf",
                b"%PDF-1.4",
                {"_omitted": "application/pdf Response Omitted"},
            ),
        ]
        for content_type, content, expected in scenarios:
            with self.subTest(content_type=content_type):
                request = self.factory.get("/")
                logger = RequestLogger(request)
                logger.response = HttpResponse(content, content_type=content_type)
                self.assertEqual(logger._sanitize_response_body(), expected)

    @patch("django_catch_a_log.request_logger.get_cid", return_value="test-cid-123")
    @override_settings(CATCHALOG_SENSITIVE_KEYS=["password", "token"], CATCHALOG_ENABLED=True)
    def test_full_lifecycle(self, mock_get_cid):
        request = self.factory.post(
            "/api/data/?q=test",
            data=json.dumps({"password": "secret"}),
            content_type="application/json",
            HTTP_X_FORWARDED_FOR="127.0.0.1",
        )
        request.user = AnonymousUser()

        logger = RequestLogger(request)
        logger.prepare_log()

        self.assertIsNotNone(logger.log_instance)

        response = HttpResponse(json.dumps({"token": "123"}), content_type="application/json")
        logger.persist_log(response)

        log = RequestLog.objects.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.cid, "test-cid-123")
        self.assertEqual(log.path, "/api/data/")
        self.assertEqual(log.method, "POST")
        self.assertEqual(log.remote_address, "127.0.0.1")
        self.assertEqual(log.status_code, 200)
        self.assertEqual(log.username_persisted, "Anonymous")

        self.assertEqual(log.body, {"password": "********"})
        self.assertEqual(log.response, {"token": "********"})
        self.assertEqual(log.query_params, {"q": ["test"]})

    @override_settings(CATCHALOG_ENABLED=True)
    def test_persist_log_with_exception(self):
        request = self.factory.get("/")

        request.user = User.objects.create(username="testuser")

        logger = RequestLogger(request)
        logger.prepare_log()

        try:
            raise ValueError("Something broke")
        except ValueError as e:
            logger.persist_log(None, exception=e)

        log = RequestLog.objects.first()

        self.assertIsNotNone(log, "Log was not saved! Check DB constraints.")
        self.assertEqual(log.status_code, 500)
        self.assertIn("ValueError: Something broke", log.exception)
        self.assertEqual(log.username_persisted, "testuser")

    def test_mask_sensitive_keys_edge_inputs(self):
        request = self.factory.get("/")
        logger = RequestLogger(request)

        self.assertIsNone(logger._mask_sensitive_keys(None))
        self.assertEqual(logger._mask_sensitive_keys({}), {})
        self.assertEqual(logger._mask_sensitive_keys([]), [])
        self.assertEqual(logger._mask_sensitive_keys("just-a-string"), "just-a-string")
        self.assertEqual(logger._mask_sensitive_keys(42), 42)

    @override_settings(CATCHALOG_SENSITIVE_KEYS=["password"])
    def test_mask_sensitive_keys_does_not_mutate_input(self):
        request = self.factory.get("/")
        logger = RequestLogger(request)

        data = {"password": "secret", "nested": {"password": "x"}}
        masked = logger._mask_sensitive_keys(data)

        self.assertEqual(masked["password"], "********")
        self.assertEqual(masked["nested"]["password"], "********")
        self.assertEqual(data["password"], "secret")
        self.assertEqual(data["nested"]["password"], "x")

    def test_sanitize_body_malformed_json_returns_empty(self):
        request = self.factory.generic("POST", "/", "{not valid json", content_type="application/json")
        logger = RequestLogger(request)
        self.assertEqual(logger._sanitize_body(), {})

    def test_sanitize_body_unknown_content_type_falls_back_to_raw(self):
        request = self.factory.generic("POST", "/", "payload-data", content_type="application/xml")
        logger = RequestLogger(request)
        result = logger._sanitize_body()
        self.assertIn("_raw_text", result)
        self.assertIn("payload-data", result["_raw_text"])

    def test_sanitize_body_missing_content_type(self):
        request = self.factory.generic("POST", "/", "anything", content_type="")
        logger = RequestLogger(request)
        # No content_type -> falls to raw branch.
        result = logger._sanitize_body()
        self.assertIn("_raw_text", result)

    def test_sanitize_response_body_binary_is_omitted(self):
        request = self.factory.get("/")
        logger = RequestLogger(request)
        logger.response = HttpResponse(b"\x00\x01\x02", content_type="application/octet-stream")
        result = logger._sanitize_response_body()
        self.assertIn("_omitted", result)

    def test_sanitize_response_body_none_returns_empty(self):
        request = self.factory.get("/")
        logger = RequestLogger(request)
        self.assertEqual(logger._sanitize_response_body(), {})

    @override_settings(CATCHALOG_REQUEST_BODY_MAX_BYTES=50)
    def test_sanitize_body_respects_size_cap(self):
        big_payload = json.dumps({"data": "x" * 200})
        request = self.factory.generic("POST", "/", big_payload, content_type="application/json")
        logger = RequestLogger(request)
        result = logger._sanitize_body()
        self.assertIn("_omitted", result)
        self.assertEqual(result["max_bytes"], 50)
        self.assertGreater(result["size_bytes"], 50)

    @override_settings(CATCHALOG_RESPONSE_BODY_MAX_BYTES=20)
    def test_sanitize_response_body_respects_size_cap(self):
        request = self.factory.get("/")
        logger = RequestLogger(request)
        logger.response = HttpResponse("x" * 500, content_type="text/plain")
        result = logger._sanitize_response_body()
        self.assertIn("_omitted", result)
        self.assertEqual(result["max_bytes"], 20)

    def test_skip_persist_based_on_settings(self):
        scenarios = [
            (False, None, 200, 0),
            (True, [400, 500], 200, 0),
            (True, [400, 500], 500, 1),
            (True, [], 200, 1),
        ]

        for enabled, statuses, response_status, expected_count in scenarios:
            with self.subTest(enabled=enabled, statuses=statuses, response_status=response_status):
                RequestLog.objects.all().delete()
                request = self.factory.get("/")

                with override_settings(CATCHALOG_ENABLED=enabled, CATCHALOG_LOG_SELECTED_STATUSES=statuses):
                    logger = RequestLogger(request)
                    logger.prepare_log()
                    response = HttpResponse(status=response_status)
                    logger.persist_log(response)

                    self.assertEqual(RequestLog.objects.count(), expected_count)
