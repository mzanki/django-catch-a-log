from unittest.mock import MagicMock, patch

from django.test import TestCase

from django_catch_a_log.model_audit import (
    _audit_m2m_changes,
    _capture_initial_state,
    _get_current_state,
    _track_model_changes,
    audit_model,
)


class MockField:
    def __init__(self, name, attname, primary_key=False):
        self.name = name
        self.attname = attname
        self.primary_key = primary_key


class MockM2MField:
    def __init__(self, name, through_model):
        self.name = name
        self.remote_field = MagicMock()
        self.remote_field.through = through_model


class MockMeta:
    def __init__(self):
        self.concrete_fields = [
            MockField("id", "id", True),
            MockField("name", "name", False),
            MockField("status", "status", False),
        ]
        self.app_label = "test_app"
        self.object_name = "TestModel"
        self.many_to_many = []


class MockInstance:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.name = kwargs.get("name", "InitialName")
        self.status = kwargs.get("status", "Active")
        self._meta = MockMeta()
        self.pk = self.id


class ModelAuditTests(TestCase):
    def test_get_current_state(self):
        instance = MockInstance()
        state = _get_current_state(instance)

        self.assertIn("name", state)
        self.assertIn("status", state)
        self.assertNotIn("id", state)  # Primary key excluded
        self.assertEqual(state["name"], "InitialName")

    def test_get_current_state_with_exclude(self):
        instance = MockInstance()
        instance._audit_exclude = ["status"]
        state = _get_current_state(instance)

        self.assertIn("name", state)
        self.assertNotIn("status", state)

    def test_capture_initial_state(self):
        instance = MockInstance()
        _capture_initial_state(None, instance)

        self.assertTrue(hasattr(instance, "_original_state"))
        self.assertEqual(instance._original_state["name"], "InitialName")

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-create")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_track_model_changes_create(self, mock_create, mock_cid):
        instance = MockInstance()
        mock_sender = MagicMock()
        mock_sender._meta = instance._meta

        _track_model_changes(sender=mock_sender, instance=instance, created=True)

        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]

        self.assertEqual(call_args["action"], "CREATE")
        self.assertEqual(call_args["model_name"], "test_app.TestModel")
        self.assertEqual(call_args["cid"], "cid-create")
        self.assertEqual(call_args["changes"]["_all_fields"]["name"], "InitialName")

    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_track_model_changes_update_no_changes(self, mock_create):
        instance = MockInstance()
        _capture_initial_state(None, instance)  # Sets _original_state

        mock_sender = MagicMock()
        mock_sender._meta = instance._meta

        _track_model_changes(sender=mock_sender, instance=instance, created=False)
        mock_create.assert_not_called()

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-update")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_track_model_changes_update_with_changes(self, mock_create, mock_cid):
        instance = MockInstance()
        _capture_initial_state(None, instance)

        # Change state
        instance.name = "NewName"

        mock_sender = MagicMock()
        mock_sender._meta = instance._meta

        _track_model_changes(sender=mock_sender, instance=instance, created=False)

        mock_create.assert_called_once()
        changes = mock_create.call_args[1]["changes"]

        self.assertIn("name", changes)
        self.assertEqual(changes["name"]["old"], "InitialName")
        self.assertEqual(changes["name"]["new"], "NewName")

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-m2m")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_audit_m2m_changes_add(self, mock_create, mock_cid):
        instance = MockInstance()
        through_mock = MagicMock()
        instance._meta.many_to_many = [MockM2MField("tags", through_mock)]

        _audit_m2m_changes(
            sender=through_mock, instance=instance, action="post_add", reverse=False, model=None, pk_set=[1, 2]
        )

        mock_create.assert_called_once()
        changes = mock_create.call_args[1]["changes"]
        self.assertIn("tags", changes)
        self.assertEqual(changes["tags"]["added"], [1, 2])
        self.assertEqual(mock_create.call_args[1]["action"], "M2M_UPDATE")

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-m2m")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_audit_m2m_changes_remove(self, mock_create, mock_cid):
        instance = MockInstance()
        through_mock = MagicMock()
        instance._meta.many_to_many = [MockM2MField("tags", through_mock)]

        _audit_m2m_changes(
            sender=through_mock, instance=instance, action="post_remove", reverse=False, model=None, pk_set=[3]
        )

        mock_create.assert_called_once()
        changes = mock_create.call_args[1]["changes"]
        self.assertEqual(changes["tags"]["removed"], [3])

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-m2m")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_audit_m2m_changes_clear(self, mock_create, mock_cid):
        instance = MockInstance()
        through_mock = MagicMock()
        instance._meta.many_to_many = [MockM2MField("tags", through_mock)]

        _audit_m2m_changes(
            sender=through_mock, instance=instance, action="post_clear", reverse=False, model=None, pk_set=set()
        )

        mock_create.assert_called_once()
        changes = mock_create.call_args[1]["changes"]
        self.assertEqual(changes["tags"]["action"], "cleared_all")

    @patch("django_catch_a_log.model_audit.post_init.connect")
    @patch("django_catch_a_log.model_audit.post_save.connect")
    @patch("django_catch_a_log.model_audit.m2m_changed.connect")
    def test_audit_model_decorator(self, mock_m2m, mock_save, mock_init):
        # We need to mock settings since decorator checks it
        with patch("django_catch_a_log.model_audit.app_settings") as mock_settings:
            mock_settings.AUDIT_LOGGING_ENABLED = True

            class DummyModel:
                _meta = MockMeta()
                _meta.many_to_many = [MockM2MField("tags", MagicMock())]

            DecoratedModel = audit_model(exclude=["status"])(DummyModel)

            self.assertEqual(DecoratedModel._audit_exclude, ["status"])
            mock_init.assert_called_once_with(_capture_initial_state, sender=DummyModel)
            mock_save.assert_called_once_with(_track_model_changes, sender=DummyModel)
            mock_m2m.assert_called_once()

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-refresh")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_track_model_changes_refreshes_original_state(self, mock_create, mock_cid):
        """After a save, _original_state must reflect the new values so that a
        subsequent save can produce a correct diff without reopening the DB row."""
        instance = MockInstance()
        _capture_initial_state(None, instance)

        instance.name = "NewName"
        mock_sender = MagicMock()
        mock_sender._meta = instance._meta
        _track_model_changes(sender=mock_sender, instance=instance, created=False)

        self.assertEqual(instance._original_state["name"], "NewName")

        # Second mutation: only now-changed fields should appear.
        instance.status = "Inactive"
        _track_model_changes(sender=mock_sender, instance=instance, created=False)

        second_call_changes = mock_create.call_args_list[1][1]["changes"]
        self.assertIn("status", second_call_changes)
        self.assertNotIn("name", second_call_changes)

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-skip")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_audit_m2m_reverse_side_is_ignored(self, mock_create, mock_cid):
        instance = MockInstance()
        through_mock = MagicMock()
        instance._meta.many_to_many = [MockM2MField("tags", through_mock)]

        _audit_m2m_changes(
            sender=through_mock, instance=instance, action="post_add", reverse=True, model=None, pk_set=[1]
        )
        mock_create.assert_not_called()

    @patch("django_catch_a_log.model_audit.get_cid", return_value="cid-skip")
    @patch("django_catch_a_log.models.AuditLog.objects.create")
    def test_audit_m2m_excluded_field_is_ignored(self, mock_create, mock_cid):
        instance = MockInstance()
        instance._audit_exclude = ["tags"]
        through_mock = MagicMock()
        instance._meta.many_to_many = [MockM2MField("tags", through_mock)]

        _audit_m2m_changes(
            sender=through_mock, instance=instance, action="post_add", reverse=False, model=None, pk_set=[1]
        )
        mock_create.assert_not_called()

    @patch("django_catch_a_log.model_audit.post_init.connect")
    def test_audit_model_decorator_disabled(self, mock_init):
        with patch("django_catch_a_log.model_audit.app_settings") as mock_settings:
            mock_settings.AUDIT_LOGGING_ENABLED = False

            class DummyModel:
                pass

            audit_model(DummyModel)
            mock_init.assert_not_called()
