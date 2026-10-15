"""Turn model attributes into display labels and values for the generic templates."""
import datetime
from decimal import Decimal

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.html import format_html
from django.utils.safestring import mark_safe


def _field(model, name):
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def column_label(model, spec):
    if isinstance(spec, (tuple, list)):
        return spec[0]
    if "__" in spec:
        spec = spec.split("__")[-1]
    f = _field(model, spec)
    if f is not None and hasattr(f, "verbose_name"):
        label = str(f.verbose_name)
        return label[:1].upper() + label[1:]
    attr = getattr(model, spec, None)
    if attr is not None and hasattr(attr, "short_description"):
        return attr.short_description
    return spec.replace("_", " ").capitalize()


def raw_value(obj, spec):
    if isinstance(spec, (tuple, list)):
        spec = spec[1]
    if callable(spec):
        return spec(obj)
    value = obj
    for part in spec.split("__"):
        if value is None:
            return None
        f = _field(type(value), part) if isinstance(value, models.Model) else None
        if f is not None and getattr(f, "choices", None):
            value = getattr(value, f"get_{part}_display")()
            continue
        if f is not None and f.many_to_many:
            return ", ".join(str(x) for x in getattr(value, part).all())
        value = getattr(value, part)
        if callable(value) and not isinstance(value, models.Model):
            value = value()
    return value


def is_numeric(obj, spec):
    if isinstance(spec, (tuple, list)):
        spec = spec[1]
    if callable(spec):
        return False
    f = _field(type(obj), spec.split("__")[0]) if "__" not in spec else None
    return isinstance(f, (models.DecimalField, models.IntegerField, models.FloatField))


def format_value(value, link=True):
    from .ui import registry

    if value is None or value == "":
        return mark_safe('<span class="muted">—</span>')
    if isinstance(value, bool):
        return mark_safe('<span class="pill ok">Yes</span>' if value else '<span class="pill">No</span>')
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, datetime.datetime):
        return value.strftime("%d %b %Y %H:%M")
    if isinstance(value, datetime.date):
        return value.strftime("%d %b %Y")
    if isinstance(value, AbstractBaseUser):
        return value.get_full_name() or value.get_username()
    if isinstance(value, models.Model):
        url = registry.url_for(value) if link else None
        if url:
            return format_html('<a href="{}">{}</a>', url, value)
        return str(value)
    if hasattr(value, "url") and hasattr(value, "name"):
        if not value:
            return mark_safe('<span class="muted">—</span>')
        return format_html('<a href="{}" target="_blank">{}</a>', value.url, value.name.split("/")[-1])
    return value


STATUS_STYLES = {
    "draft": "", "new": "", "open": "info", "submitted": "warn", "pending": "warn",
    "pending_approval": "warn", "pm_approval": "warn", "sm_approval": "warn", "under_review": "warn",
    "approved": "ok", "qualified": "ok", "posted": "ok", "active": "ok", "won": "ok", "accepted": "ok",
    "received": "ok", "issued": "ok", "paid": "ok", "closed": "dark", "completed": "ok", "processed": "info",
    "sent": "info", "partial": "info", "partially_received": "info", "partially_issued": "info",
    "rejected": "bad", "cancelled": "bad", "lost": "bad", "on_hold": "warn", "matched": "ok",
    "discrepancy": "bad", "cleared": "ok", "bounced": "bad", "estimation": "info", "quoted": "info",
    "ordered": "info", "rfq": "info", "revised": "",
}


def status_pill(obj):
    status = getattr(obj, "status", None)
    if status is None:
        return ""
    label = obj.get_status_display() if hasattr(obj, "get_status_display") else status
    return format_html('<span class="pill {}">{}</span>', STATUS_STYLES.get(status, ""), label)
