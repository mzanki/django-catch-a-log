import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import m2m_changed, post_init, post_save

from .app_settings import app_settings
from .cid import get_cid


def _get_current_state(instance):
    """Helper to extract current DB state, ignoring excluded fields and relational objects."""
    exclude_fields = getattr(instance, "_audit_exclude", [])
    return {
        f.name: getattr(instance, f.attname)
        for f in instance._meta.concrete_fields
        if not f.primary_key and f.name not in exclude_fields
    }


def _capture_initial_state(sender, instance, **kwargs):
    instance._original_state = _get_current_state(instance)


def _track_model_changes(sender, instance, created, **kwargs):
    action = "CREATE" if created else "UPDATE"
    changes = {}

    if created:
        changes = {"_all_fields": _get_current_state(instance)}
    else:
        current_state = _get_current_state(instance)
        original_state = getattr(instance, "_original_state", {})

        for field, old_value in original_state.items():
            new_value = current_state.get(field)
            if old_value != new_value:
                changes[field] = {"old": old_value, "new": new_value}

    if changes:
        from .models import AuditLog

        safe_changes = json.loads(json.dumps(changes, cls=DjangoJSONEncoder))
        full_model_name = f"{sender._meta.app_label}.{sender._meta.object_name}"

        AuditLog.objects.create(
            cid=get_cid() or "",
            action=action,
            model_name=full_model_name,
            object_id=str(instance.pk),
            changes=safe_changes,
        )

    instance._original_state = _get_current_state(instance)


def _audit_m2m_changes(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action not in ["post_add", "post_remove", "post_clear"] or reverse:
        return

    exclude_fields = getattr(instance, "_audit_exclude", [])

    field_name = None
    for field in instance._meta.many_to_many:
        if field.remote_field.through == sender:
            field_name = field.name
            break

    if not field_name or field_name in exclude_fields:
        return

    changes = {}
    if action == "post_add":
        changes[field_name] = {"added": list(pk_set)}
    elif action == "post_remove":
        changes[field_name] = {"removed": list(pk_set)}
    elif action == "post_clear":
        changes[field_name] = {"action": "cleared_all"}
    from .models import AuditLog

    full_model_name = f"{instance._meta.app_label}.{instance._meta.object_name}"
    AuditLog.objects.create(
        cid=get_cid() or "",
        action="M2M_UPDATE",
        model_name=full_model_name,
        object_id=str(instance.pk),
        changes=changes,
    )


def audit_model(*args, **kwargs):
    """
    Class Decorator to automatically track model changes.
    Can be used as @audit_model or @audit_model(exclude=['field1', 'field2'])
    """

    def wrapper(cls):
        if not app_settings.AUDIT_LOGGING_ENABLED:
            return cls
        cls._audit_exclude = kwargs.get("exclude", [])

        post_init.connect(_capture_initial_state, sender=cls)
        post_save.connect(_track_model_changes, sender=cls)

        for field in cls._meta.many_to_many:
            m2m_changed.connect(_audit_m2m_changes, sender=field.remote_field.through)

        return cls

    if len(args) == 1 and callable(args[0]):
        return wrapper(args[0])

    return wrapper
