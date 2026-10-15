from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from core.models import ZERO
from core.services import q2, require_status
from core.workflow import approve_step, open_detail, set_status, submit_for_approval

from .models import DepreciationLine, FixedAsset
from .services import ctl, entries_for, post_journal, post_manual, reverse_entry


# --- manual vouchers -----------------------------------------------------------

def je_post(request, je):
    post_manual(je)
    return f"{je.get_voucher_type_display()} posted."


def je_reverse(request, je):
    if je.reversal_of_id or je.status != "posted" or je.reversals.exists():
        raise ValidationError("Only posted, original entries can be reversed.")
    rev = reverse_entry(je, narration=f"Reversal of {je.number}: {request.action_comment}")
    return open_detail(request, rev, "Reversal posted.")


# --- customer invoices ----------------------------------------------------------

def invoice_post(request, inv):
    require_status(inv, "draft")
    inv.recalc()
    if inv.gross_amount <= 0:
        raise ValidationError("Invoice amount must be positive. Check the cumulative % against earlier invoices.")
    c = ctl()
    rate = inv.exchange_rate or Decimal("1")
    common = {"customer": inv.customer, "project": inv.project}
    lines = [{"account": c.require("receivable"), "debit": inv.total, **common, "description": inv.description}]
    if inv.invoice_type == "advance":
        lines += [{"account": c.require("customer_advance"), "credit": inv.gross_amount, **common},
                  {"account": c.require("vat_output"), "credit": inv.vat_amount}]
    elif inv.invoice_type == "retention":
        lines += [{"account": c.require("retention_receivable"), "credit": inv.gross_amount, **common}]
    else:
        lines += [
            {"account": c.require("retention_receivable"), "debit": inv.retention_amount, **common},
            {"account": c.require("customer_advance"), "debit": inv.advance_recovery, **common},
            {"account": c.require("contract_revenue"), "credit": inv.gross_amount, **common},
            {"account": c.require("vat_output"), "credit": inv.vat_amount},
        ]
    entry = post_journal(inv.date, lines, "SI", f"{inv.get_invoice_type_display()} invoice {inv.number}",
                         source=inv, reference=inv.number, currency=inv.currency, rate=rate)
    inv.journal = entry
    inv.status = "posted"
    inv.save(update_fields=["journal", "status"])
    return f"Invoice posted: net receivable {inv.total:,.2f}."


def invoice_cancel(request, inv):
    if inv.paid_amount:
        raise ValidationError("Invoice has receipts allocated; reverse them first.")
    for e in entries_for(inv).filter(status="posted", reversal_of__isnull=True, reversals__isnull=True):
        reverse_entry(e, narration=f"Cancel {inv.number}: {request.action_comment}")
    set_status(inv, "cancelled")


# --- receipts --------------------------------------------------------------------

def _receipt_debit_account(r, c):
    if r.mode == "pdc":
        return c.require("pdc_receivable")
    if r.mode == "cash":
        return c.require("cash")
    if not r.bank_account:
        raise ValidationError("Choose the bank account.")
    return r.bank_account.account


def receipt_post(request, r):
    require_status(r, "draft")
    if r.amount <= 0:
        raise ValidationError("Amount must be positive.")
    allocations = list(r.allocations.select_related("invoice"))
    if sum((a.amount for a in allocations), ZERO) > r.amount:
        raise ValidationError("Allocations exceed the receipt amount.")
    for a in allocations:
        if a.invoice.customer_id != r.customer_id:
            raise ValidationError(f"{a.invoice} belongs to another customer.")
        if a.amount > a.invoice.balance:
            raise ValidationError(f"{a.invoice}: allocation {a.amount:,.2f} exceeds balance {a.invoice.balance:,.2f}.")
    c = ctl()
    post_journal(r.date, [
        {"account": _receipt_debit_account(r, c), "debit": r.amount, "description": f"{r.get_mode_display()} {r.cheque_no}"},
        {"account": c.require("receivable"), "credit": r.amount, "customer": r.customer, "project": r.project},
    ], "RV", f"Receipt {r.number} from {r.customer.name}", source=r, reference=r.reference or r.cheque_no)
    for a in allocations:
        a.invoice.paid_amount += a.amount
        a.invoice.save(update_fields=["paid_amount"])
    set_status(r, "pdc" if r.mode == "pdc" else "posted")


def receipt_clear(request, r):
    if not r.bank_account:
        raise ValidationError("Choose the bank account the PDC was deposited to (edit is locked; set it in admin).")
    c = ctl()
    post_journal(r.cheque_date or r.date, [
        {"account": r.bank_account.account, "debit": r.amount, "description": f"PDC {r.cheque_no} cleared"},
        {"account": c.require("pdc_receivable"), "credit": r.amount},
    ], "CV", f"PDC cleared {r.number}", source=r)
    set_status(r, "cleared")


def receipt_bounce(request, r):
    c = ctl()
    credit = c.require("pdc_receivable") if r.status == "pdc" else _receipt_debit_account(r, c)
    post_journal(r.date, [
        {"account": c.require("receivable"), "debit": r.amount, "customer": r.customer, "project": r.project,
         "description": f"Cheque {r.cheque_no} bounced"},
        {"account": credit, "credit": r.amount},
    ], "JV", f"Bounced cheque {r.number}: {request.action_comment}", source=r)
    for a in r.allocations.select_related("invoice"):
        a.invoice.paid_amount -= a.amount
        a.invoice.save(update_fields=["paid_amount"])
    set_status(r, "bounced")


# --- vendor invoices: 3-way match ---------------------------------------------------

PRICE_TOLERANCE = Decimal("0.005")


def vinv_match(request, inv):
    inv.recalc()
    notes = []
    ok = True
    if not inv.lines.exists():
        raise ValidationError("Add invoice lines.")
    if inv.purchase_order and inv.purchase_order.vendor_id != inv.vendor_id:
        notes.append("PO belongs to another vendor.")
        ok = False
    for l in inv.lines.select_related("po_line__product"):
        if not l.po_line:
            if not l.account:
                l.match_result = "No PO line: choose an expense account"
                ok = False
            else:
                l.match_result = "Non-PO expense"
            l.save(update_fields=["match_result"])
            continue
        pl = l.po_line
        available = pl.received_qty - pl.invoiced_qty
        issues = []
        if l.qty > available:
            issues.append(f"qty {l.qty:g} > received-not-invoiced {available:g}")
        if pl.rate and abs(l.rate - pl.rate) > pl.rate * PRICE_TOLERANCE:
            issues.append(f"price {l.rate:,.2f} ≠ PO {pl.rate:,.2f}")
        l.match_result = "; ".join(issues) if issues else "OK: PO = GRN = invoice"
        if issues:
            ok = False
            notes.append(f"{pl.product.code}: {l.match_result}")
        l.save(update_fields=["match_result"])
    inv.match_notes = "\n".join(notes) or "All lines match PO and GRN."
    inv.status = "matched" if ok else "discrepancy"
    inv.save(update_fields=["match_notes", "status"])
    return "3-way match passed." if ok else "Discrepancies flagged: see the match notes."


def vinv_accept_discrepancy(request, inv):
    inv.discrepancy_approved = True
    inv.match_notes += f"\nDiscrepancy accepted by {request.user}: {request.action_comment}"
    inv.status = "matched"
    inv.save(update_fields=["discrepancy_approved", "match_notes", "status"])


def vinv_post(request, inv):
    require_status(inv, "matched")
    c = ctl()
    rate = inv.exchange_rate or Decimal("1")
    lines = []
    for l in inv.lines.select_related("po_line__order", "account"):
        amount = q2(l.amount * rate)
        if l.po_line:
            grni_value = q2(l.qty * l.po_line.rate * (l.po_line.order.exchange_rate or 1))
            lines.append({"account": c.require("grni"), "debit": grni_value, "vendor": inv.vendor,
                          "description": f"{l.po_line.product.code} × {l.qty:g}"})
            if amount != grni_value:
                lines.append({"account": c.require("price_variance"), "debit": amount - grni_value,
                              "project": inv.project, "description": "Price / exchange variance"})
            l.po_line.invoiced_qty += l.qty
            l.po_line.save(update_fields=["invoiced_qty"])
        else:
            lines.append({"account": l.account, "debit": amount, "project": inv.project, "vendor": inv.vendor,
                          "description": l.description})
    vat = q2(inv.vat_amount * rate)
    lines.append({"account": c.require("vat_input"), "debit": vat})
    lines.append({"account": c.require("payable"), "credit": q2(inv.subtotal * rate) + vat, "vendor": inv.vendor,
                  "project": inv.project, "description": f"Vendor inv {inv.vendor_invoice_no}"})
    entry = post_journal(inv.date, lines, "PI", f"Vendor invoice {inv.vendor_invoice_no} ({inv.vendor.name})",
                         source=inv, reference=inv.vendor_invoice_no)
    inv.journal = entry
    inv.status = "posted"
    inv.save(update_fields=["journal", "status"])
    return "Vendor invoice posted to accounts payable."


# --- vendor payments -------------------------------------------------------------

def vpay_submit(request, p):
    if p.amount <= 0:
        raise ValidationError("Amount must be positive.")
    submit_for_approval(p)


def vpay_approve(request, p):
    approve_step(request, p)


def vpay_post(request, p):
    require_status(p, "approved")
    c = ctl()
    allocations = list(p.allocations.select_related("invoice"))
    if sum((a.amount for a in allocations), ZERO) > p.amount:
        raise ValidationError("Allocations exceed the payment amount.")
    for a in allocations:
        if a.amount > a.invoice.balance:
            raise ValidationError(f"{a.invoice}: allocation exceeds balance {a.invoice.balance:,.2f}.")
    if p.mode in ("cheque", "pdc"):
        if not p.bank_account:
            raise ValidationError("Choose the bank account for the cheque.")
        if not p.cheque_no:
            p.cheque_no = str(p.bank_account.next_cheque_no)
            p.bank_account.next_cheque_no += 1
            p.bank_account.save(update_fields=["next_cheque_no"])
    if p.mode == "pdc":
        credit = c.require("pdc_payable")
    elif p.mode == "cash":
        credit = c.require("cash")
    else:
        if not p.bank_account:
            raise ValidationError("Choose the bank account.")
        credit = p.bank_account.account
    post_journal(p.date, [
        {"account": c.require("payable"), "debit": p.amount, "vendor": p.vendor},
        {"account": credit, "credit": p.amount, "description": f"{p.get_mode_display()} {p.cheque_no}"},
    ], "PV", f"Payment {p.number} to {p.vendor.name}", source=p, reference=p.cheque_no)
    for a in allocations:
        a.invoice.paid_amount += a.amount
        a.invoice.save(update_fields=["paid_amount"])
    if not p.payee_name:
        p.payee_name = p.vendor.name
    p.status = "posted"
    p.save(update_fields=["cheque_no", "payee_name", "status"])
    return f"Payment posted{f' — cheque {p.cheque_no}' if p.cheque_no else ''}."


def vpay_clear(request, p):
    post_journal(p.cheque_date or p.date, [
        {"account": ctl().require("pdc_payable"), "debit": p.amount},
        {"account": p.bank_account.account, "credit": p.amount, "description": f"PDC {p.cheque_no} presented"},
    ], "CV", f"PDC cleared {p.number}", source=p)
    set_status(p, "cleared")


# --- depreciation ----------------------------------------------------------------

def dep_compute(request, run):
    run.lines.all().delete()
    total = ZERO
    for a in FixedAsset.objects.filter(status="active", purchase_date__lte=run.period_end):
        done = a.depreciation_lines.filter(run__status="posted").aggregate(t=Sum("amount"))["t"] or ZERO
        if a.depreciation_lines.filter(run__status="posted", run__period_end=run.period_end).exists():
            continue
        remaining = a.cost - a.salvage_value - done
        amount = min(a.monthly_depreciation, remaining)
        if amount > 0:
            DepreciationLine.objects.create(run=run, asset=a, amount=amount)
            total += amount
    run.total = total
    run.save(update_fields=["total"])
    return f"Depreciation computed for {run.lines.count()} asset(s): {total:,.2f}."


def dep_post(request, run):
    if not run.lines.exists():
        raise ValidationError("Compute the run first.")
    journal = []
    for l in run.lines.select_related("asset__category"):
        cat = l.asset.category
        journal += [{"account": cat.expense_account, "debit": l.amount, "project": l.asset.project,
                     "description": l.asset.code},
                    {"account": cat.accumulated_account, "credit": l.amount, "description": l.asset.code}]
    post_journal(run.period_end, journal, "DEP", f"Depreciation {run.period_end:%b %Y}", source=run)
    set_status(run, "posted")
