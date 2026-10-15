"""The only entry point that writes to the general ledger."""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from core.models import ZERO
from core.services import q2

from .models import ControlAccounts, JournalEntry, JournalLine


def ctl():
    return ControlAccounts.get()


def post_journal(date, lines, voucher_type="JV", narration="", source=None, reference="",
                 currency=None, rate=Decimal("1")):
    """Create a posted, balanced journal entry.

    lines: iterable of dicts with account, debit|credit (transaction currency) and optional
    project / customer / vendor / employee / description. Zero lines are dropped.
    """
    rate = rate or Decimal("1")
    clean = []
    for l in lines:
        debit = q2(l.get("debit") or 0)
        credit = q2(l.get("credit") or 0)
        if debit < 0:
            debit, credit = ZERO, credit - debit
        if credit < 0:
            debit, credit = debit - credit, ZERO
        if debit == 0 and credit == 0:
            continue
        if l["account"] is None:
            raise ValidationError("A posting line has no GL account. Check the control account mapping.")
        if l["account"].is_group:
            raise ValidationError(f"Cannot post to group account {l['account']}.")
        clean.append({**l, "debit": debit, "credit": credit})
    if not clean:
        return None
    total_d = sum(l["debit"] for l in clean)
    total_c = sum(l["credit"] for l in clean)
    if total_d != total_c:
        raise ValidationError(f"Journal is not balanced: debit {total_d} ≠ credit {total_c}.")
    entry = JournalEntry(date=date, voucher_type=voucher_type, narration=narration[:300], reference=reference[:80],
                         currency=currency, exchange_rate=rate, status="posted")
    if source is not None:
        entry.content_type = ContentType.objects.get_for_model(source)
        entry.object_id = source.pk
    entry.save()
    base_total = ZERO
    for l in clean:
        bd, bc = q2(l["debit"] * rate), q2(l["credit"] * rate)
        base_total += bd
        JournalLine.objects.create(
            entry=entry, account=l["account"], description=(l.get("description") or "")[:200],
            debit=l["debit"], credit=l["credit"], base_debit=bd, base_credit=bc,
            project=l.get("project"), customer=l.get("customer"), vendor=l.get("vendor"),
            employee=l.get("employee"),
        )
    # absorb base-currency rounding on the last line
    agg_d = sum(x.base_debit for x in entry.lines.all())
    agg_c = sum(x.base_credit for x in entry.lines.all())
    if agg_d != agg_c:
        last = entry.lines.order_by("-id").first()
        if last.base_debit:
            last.base_debit += agg_c - agg_d
        else:
            last.base_credit += agg_d - agg_c
        last.save()
    entry.total = max(agg_d, agg_c)
    entry.save(update_fields=["total"])
    return entry


def entries_for(source):
    return JournalEntry.objects.filter(content_type=ContentType.objects.get_for_model(source), object_id=source.pk)


def reverse_entry(entry, date=None, narration=None):
    lines = [{"account": l.account, "debit": l.credit, "credit": l.debit, "project": l.project,
              "customer": l.customer, "vendor": l.vendor, "employee": l.employee, "description": l.description}
             for l in entry.lines.all()]
    rev = post_journal(date or entry.date, lines, entry.voucher_type, narration or f"Reversal of {entry.number}",
                       source=entry.source, reference=entry.number, currency=entry.currency, rate=entry.exchange_rate)
    rev.reversal_of = entry
    rev.save(update_fields=["reversal_of"])
    return rev


def post_manual(entry):
    """Post a draft manual voucher created in the UI."""
    lines = list(entry.lines.all())
    if not lines:
        raise ValidationError("Add at least two lines.")
    entry.recalc()
    d = sum(l.debit for l in lines)
    c = sum(l.credit for l in lines)
    if d != c:
        raise ValidationError(f"Voucher is not balanced: debit {d:,.2f} ≠ credit {c:,.2f}.")
    for l in lines:
        if l.account.is_group:
            raise ValidationError(f"Cannot post to group account {l.account}.")
    entry.status = "posted"
    entry.save(update_fields=["status"])
