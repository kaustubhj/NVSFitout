"""Cross-cutting services: numbering, audit trail, approvals."""
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import ApprovalLog, ApprovalRule, AuditLog, Sequence

TWO = Decimal("0.01")


def q2(value):
    return Decimal(value or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def next_number(key, prefix):
    with transaction.atomic():
        seq, _ = Sequence.objects.select_for_update().get_or_create(key=key, defaults={"prefix": prefix})
        value = seq.next_value
        seq.next_value = value + 1
        seq.save(update_fields=["next_value"])
    return f"{seq.prefix}{value:0{seq.padding}d}"


def audit(obj, action, user=None, changes=None):
    if user is None:
        from .middleware import get_current_user

        user = get_current_user()
    AuditLog.objects.create(
        content_type=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
        object_repr=str(obj)[:200],
        action=action,
        changes=changes or {},
        user=user if user is not None and user.is_authenticated else None,
    )


def user_in_group(user, group_name):
    return user.is_superuser or user.groups.filter(name=group_name).exists()


# --- approvals ---------------------------------------------------------------

def required_rules(doc_type, amount):
    rules = ApprovalRule.objects.filter(doc_type=doc_type, min_amount__lte=amount).select_related("group")
    return [r for r in rules if r.max_amount is None or amount <= r.max_amount]


def approval_logs(obj):
    return ApprovalLog.objects.filter(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk
    ).select_related("user")


def pending_rule(obj):
    """Next approval rule not yet satisfied for obj, or None when fully approved."""
    approved_levels = set(approval_logs(obj).filter(decision="approved").values_list("level", flat=True))
    for rule in sorted(required_rules(obj.APPROVAL_DOC_TYPE, obj.approval_amount()), key=lambda r: r.level):
        if rule.level not in approved_levels:
            return rule
    return None


def reset_approvals(obj):
    approval_logs(obj).delete()


def record_decision(obj, user, decision, comment=""):
    """Approve or reject the pending level. Returns True when the document is fully approved."""
    rule = pending_rule(obj)
    if rule is None:
        return True
    if not user_in_group(user, rule.group.name):
        raise PermissionDenied(f"Level {rule.level} approval needs the '{rule.group.name}' role.")
    ApprovalLog.objects.create(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk,
        level=rule.level, group_name=rule.group.name, decision=decision, comment=comment, user=user,
    )
    audit(obj, f"{decision} level {rule.level}", user)
    if decision == "rejected":
        return False
    return pending_rule(obj) is None


def require_status(obj, *statuses):
    if obj.status not in statuses:
        labels = ", ".join(statuses)
        raise ValidationError(f"This action needs status {labels}; current status is {obj.get_status_display()}.")
