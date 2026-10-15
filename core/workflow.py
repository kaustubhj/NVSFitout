"""Small helpers shared by module workflow actions."""
from django.contrib import messages
from django.http import HttpResponseRedirect

from .services import audit, pending_rule, record_decision, reset_approvals
from .ui import registry


def open_edit(request, obj, note=None):
    if note:
        messages.success(request, note)
    return HttpResponseRedirect(registry.url_for(obj) + "edit/")


def open_detail(request, obj, note=None):
    if note:
        messages.success(request, note)
    return HttpResponseRedirect(registry.url_for(obj))


def set_status(obj, status):
    obj.status = status
    obj.save(update_fields=["status"])


def submit_for_approval(obj, pending_status="pending_approval", approved_status="approved"):
    """Reset any earlier approvals and move to the first pending level (or straight to approved)."""
    reset_approvals(obj)
    rule = pending_rule(obj)
    set_status(obj, pending_status if rule else approved_status)
    return rule


def approve_step(request, obj, approved_status="approved", rejected_status="rejected", status_for_rule=None):
    decision = "rejected" if request.POST.get("decision") == "reject" else "approved"
    done = record_decision(obj, request.user, decision, getattr(request, "action_comment", ""))
    if decision == "rejected":
        set_status(obj, rejected_status)
        return False
    if done:
        set_status(obj, approved_status)
        return True
    if status_for_rule:
        set_status(obj, status_for_rule(pending_rule(obj)))
    return False


def reject_step(request, obj, rejected_status="rejected"):
    record_decision(obj, request.user, "rejected", getattr(request, "action_comment", ""))
    set_status(obj, rejected_status)


def can_approve(user, obj):
    rule = pending_rule(obj)
    if rule is None:
        return False
    return user.is_superuser or user.groups.filter(pk=rule.group_id).exists()


__all__ = ["open_edit", "open_detail", "set_status", "submit_for_approval", "approve_step", "reject_step",
           "can_approve", "audit"]
