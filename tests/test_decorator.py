import asyncio
import uuid
from unittest import TestCase

from django_catch_a_log.cid import _correlation_id, get_cid
from django_catch_a_log.decorators import with_correlation_id


@with_correlation_id
def dummy_background_task(*args, **kwargs):
    return {
        "active_cid": get_cid(),
        "received_args": args,
        "received_kwargs": kwargs,
    }


class WithCorrelationIdTests(TestCase):
    def setUp(self):
        self.token = _correlation_id.set(None)

    def tearDown(self):
        _correlation_id.reset(self.token)

    def test_provided_cid_is_set_and_popped(self):
        scenarios = [
            ("explicit-cid-123", ("arg1",), {"other": "val"}),
            ("another-cid-456", (), {}),
        ]

        for passed_cid, args, kwargs in scenarios:
            with self.subTest(passed_cid=passed_cid):
                call_kwargs = {"cid": passed_cid, **kwargs}

                result = dummy_background_task(*args, **call_kwargs)

                self.assertEqual(result["active_cid"], passed_cid)
                self.assertEqual(result["received_args"], args)
                self.assertEqual(result["received_kwargs"], kwargs)
                self.assertNotIn("cid", result["received_kwargs"])

    def test_missing_cid_generates_new_uuid(self):
        scenarios = [
            (("arg1", "arg2"), {"key": "value"}),
            ((), {}),
        ]

        for args, kwargs in scenarios:
            with self.subTest(args=args, kwargs=kwargs):
                _correlation_id.set(None)

                result = dummy_background_task(*args, **kwargs)

                active_cid = result["active_cid"]
                self.assertIsNotNone(active_cid)
                self.assertIsInstance(active_cid, str)

                try:
                    uuid.UUID(active_cid, version=4)
                    is_valid_uuid = True
                except ValueError:
                    is_valid_uuid = False

                self.assertTrue(is_valid_uuid)
                self.assertEqual(result["received_args"], args)
                self.assertEqual(result["received_kwargs"], kwargs)

    def test_decorator_preserves_metadata(self):
        @with_correlation_id
        def named_task():
            """Task docstring."""
            pass

        self.assertEqual(named_task.__name__, "named_task")
        self.assertEqual(named_task.__doc__, "Task docstring.")

    def test_sync_decorator_resets_cid_after_return(self):
        @with_correlation_id
        def task():
            return get_cid()

        result = task(cid="sync-cid-reset")
        self.assertEqual(result, "sync-cid-reset")
        self.assertIsNone(get_cid())

    def test_sync_decorator_resets_cid_on_exception(self):
        @with_correlation_id
        def task():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            task(cid="err-cid")
        self.assertIsNone(get_cid())


class WithCorrelationIdAsyncTests(TestCase):
    def setUp(self):
        self.token = _correlation_id.set(None)

    def tearDown(self):
        _correlation_id.reset(self.token)

    def test_async_decorator_uses_provided_cid(self):
        @with_correlation_id
        async def task():
            return get_cid()

        result = asyncio.run(task(cid="async-cid-123"))
        self.assertEqual(result, "async-cid-123")
        self.assertIsNone(get_cid())

    def test_async_decorator_generates_cid_when_missing(self):
        @with_correlation_id
        async def task():
            return get_cid()

        result = asyncio.run(task())
        uuid.UUID(result, version=4)
        self.assertIsNone(get_cid())

    def test_async_decorator_resets_cid_on_exception(self):
        @with_correlation_id
        async def task():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            asyncio.run(task(cid="async-err"))
        self.assertIsNone(get_cid())

    def test_async_decorator_preserves_metadata(self):
        @with_correlation_id
        async def async_named():
            """Async docstring."""
            pass

        self.assertEqual(async_named.__name__, "async_named")
        self.assertEqual(async_named.__doc__, "Async docstring.")
        self.assertTrue(asyncio.iscoroutinefunction(async_named))
