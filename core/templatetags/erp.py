from decimal import Decimal

from django import template

from core.display import format_value, status_pill

register = template.Library()


@register.filter
def fmt(value):
    return format_value(value)


@register.filter
def isnum(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


@register.filter
def money(value):
    try:
        return f"{Decimal(value or 0):,.2f}"
    except Exception:
        return value


@register.filter
def pill(obj):
    return status_pill(obj)


@register.filter
def get(d, key):
    try:
        return d[key]
    except Exception:
        return getattr(d, key, "")


@register.filter
def words(value):
    from core.numwords import amount_words

    return amount_words(value or 0)
