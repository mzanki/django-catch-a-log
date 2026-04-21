import threading
import uuid
from unittest import TestCase

from django_catch_a_log.cid import _correlation_id, generate_new_cid, get_cid, set_cid


class CidTests(TestCase):
    def setUp(self):
        self.token = _correlation_id.set(None)

    def tearDown(self):
        _correlation_id.reset(self.token)

    def test_generate_new_cid_format(self):
        cid = generate_new_cid()
        self.assertIsInstance(cid, str)

        try:
            parsed_uuid = uuid.UUID(cid, version=4)
            is_valid = str(parsed_uuid) == cid
        except ValueError:
            is_valid = False

        self.assertTrue(is_valid)

    def test_generate_new_cid_uniqueness(self):
        self.assertNotEqual(generate_new_cid(), generate_new_cid())

    def test_get_cid_default(self):
        self.assertIsNone(get_cid())

    def test_set_and_get_cid(self):
        scenarios = [
            "test-id-123",
            "uuid-format-string-here",
            "",
        ]

        for cid_value in scenarios:
            with self.subTest(cid_value=cid_value):
                set_cid(cid_value)
                self.assertEqual(get_cid(), cid_value)

    def test_context_isolation_across_threads(self):
        set_cid("main-thread-id")

        thread_results = {}

        def worker():
            thread_results["initial_get"] = get_cid()
            set_cid("worker-thread-id")
            thread_results["after_set"] = get_cid()

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertIsNone(thread_results["initial_get"])
        self.assertEqual(thread_results["after_set"], "worker-thread-id")
        self.assertEqual(get_cid(), "main-thread-id")
