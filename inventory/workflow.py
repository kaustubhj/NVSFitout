from decimal import Decimal

from django.core.exceptions import ValidationError

from accounts.services import ctl, post_journal
from core.models import ZERO
from core.services import record_decision, require_status
from core.workflow import approve_step, open_detail, open_edit, set_status, submit_for_approval

from .models import (InternalRequest, InternalRequestLine, StockAdjustment, StockAdjustmentLine, StockBalance,
                     StockIssue, StockIssueLine)
from .services import expense_account, move_stock, stock_account


# --- material requisition ------------------------------------------------------

def mr_submit(request, mr):
    if not mr.lines.exists():
        raise ValidationError("Add at least one item.")
    set_status(mr, "submitted")


def mr_stock_check(request, mr):
    """Check availability; shortfall raises a purchase requisition."""
    from procurement.models import PurchaseRequisition, PurchaseRequisitionLine

    shortfalls = []
    for line in mr.lines.select_related("product"):
        available = line.product.qty_on_hand(mr.warehouse)
        line.available_at_check = available
        line.save(update_fields=["available_at_check"])
        short = line.pending_qty - available - line.purchase_qty
        if short > 0 and line.product.is_stock:
            shortfalls.append((line, short))
        elif short > 0:  # services / subcontract always go to purchase
            shortfalls.append((line, short))
    if not shortfalls:
        return "All items are available in store. Raise an internal request to draw them."
    pr = PurchaseRequisition.objects.create(source="site", project=mr.project, material_requisition=mr,
                                            required_date=mr.required_date, warehouse=mr.warehouse,
                                            remarks=f"Shortfall from {mr.number}")
    for line, short in shortfalls:
        PurchaseRequisitionLine.objects.create(requisition=pr, product=line.product, qty=short,
                                               estimated_rate=line.product.standard_cost,
                                               required_date=mr.required_date)
        line.purchase_qty += short
        line.save(update_fields=["purchase_qty"])
    pr.recalc()
    return open_detail(request, pr, f"Shortfall on {len(shortfalls)} item(s): purchase requisition {pr.number} raised.")


def mr_internal_request(request, mr):
    ir = InternalRequest.objects.create(requisition=mr, project=mr.project, warehouse=mr.warehouse)
    n = 0
    for line in mr.lines.select_related("product"):
        if not line.product.is_stock:
            continue
        qty = min(line.pending_qty, line.product.qty_on_hand(mr.warehouse))
        if qty > 0:
            InternalRequestLine.objects.create(request=ir, mr_line=line, product=line.product, qty=qty,
                                               bin=line.product.default_bin)
            n += 1
    if not n:
        ir.delete()
        raise ValidationError("Nothing pending is available in store. Run a stock check to raise a purchase requisition.")
    return open_detail(request, ir, "Internal request created to draw available stock from the store.")


def mr_close(request, mr):
    set_status(mr, "closed")


# --- internal request ------------------------------------------------------------

def ir_release(request, ir):
    set_status(ir, "released")


def ir_issue(request, ir):
    if ir.project is None:
        raise ValidationError("An internal request must be for a project before it can be issued.")
    siv = StockIssue.objects.create(project=ir.project, warehouse=ir.warehouse, requisition=ir.requisition,
                                    internal_request=ir)
    for l in ir.lines.all():
        StockIssueLine.objects.create(issue=siv, mr_line=l.mr_line, product=l.product, qty=l.qty, bin=l.bin)
    return open_detail(request, siv, "Stock issue voucher prepared. Check quantities and post it.")


# --- stock issue voucher -------------------------------------------------------

def siv_post(request, siv):
    require_status(siv, "draft")
    journal = []
    total = ZERO
    for l in siv.lines.select_related("product"):
        move = move_stock(l.product, siv.warehouse, -l.qty, date=siv.date, move_type="issue", source=siv,
                          project=siv.project, bin=l.bin)
        l.unit_cost = move.unit_cost
        l.value = -move.value
        l.save(update_fields=["unit_cost", "value"])
        total += l.value
        journal += [
            {"account": expense_account(l.product), "debit": l.value, "project": siv.project,
             "description": f"{l.product.code} × {l.qty:g}"},
            {"account": stock_account(l.product), "credit": l.value, "description": f"{l.product.code} issue"},
        ]
        if l.mr_line_id:
            l.mr_line.issued_qty += l.qty
            l.mr_line.save(update_fields=["issued_qty"])
    post_journal(siv.date, journal, "STK", f"Stock issue {siv.number} to {siv.project.code}", source=siv)
    siv.total_value = total
    siv.status = "posted"
    siv.save(update_fields=["total_value", "status"])
    if siv.requisition_id:
        siv.requisition.update_status()
    if siv.internal_request_id:
        set_status(siv.internal_request, "issued")
    return f"Issued {total:,.2f} of material to {siv.project.code}."


# --- goods receipt -------------------------------------------------------------

def grn_post(request, grn):
    require_status(grn, "draft")
    po = grn.purchase_order
    rate_fx = po.exchange_rate or Decimal("1")
    journal = []
    total = ZERO
    lines = list(grn.lines.select_related("product", "po_line"))
    if not lines:
        raise ValidationError("No lines to receive.")
    for l in lines:
        if l.accepted_qty + l.rejected_qty != l.received_qty:
            raise ValidationError(f"{l.product.code}: accepted + rejected must equal received.")
        if l.accepted_qty > l.po_line.pending_qty:
            raise ValidationError(f"{l.product.code}: accepting {l.accepted_qty:g} but only "
                                  f"{l.po_line.pending_qty:g} is pending on the PO.")
        unit_cost = l.po_line.rate * rate_fx
        value = round(unit_cost * l.accepted_qty, 2)
        if l.accepted_qty > 0:
            if l.product.is_stock:
                move_stock(l.product, grn.warehouse, l.accepted_qty, unit_cost, date=grn.date, move_type="receipt",
                           source=grn, project=po.project, bin=l.bin or l.product.default_bin)
                debit_acc, project = stock_account(l.product), None
            else:
                debit_acc, project = expense_account(l.product), po.project
            journal += [
                {"account": debit_acc, "debit": value, "project": project, "description": f"{l.product.code} × {l.accepted_qty:g}"},
                {"account": ctl().require("grni"), "credit": value, "vendor": po.vendor, "description": f"GRNI {po.number}"},
            ]
        l.unit_cost = unit_cost
        l.value = value
        l.qc_status = "passed" if not l.rejected_qty else ("failed" if not l.accepted_qty else "partial")
        l.save()
        l.po_line.received_qty += l.accepted_qty
        l.po_line.save(update_fields=["received_qty"])
        total += value
    post_journal(grn.date, journal, "STK", f"GRN {grn.number} against {po.number}", source=grn)
    grn.total_value = total
    grn.status = "posted"
    grn.save(update_fields=["total_value", "status"])
    po.update_receipt_status()
    rejected = sum(l.rejected_qty for l in lines)
    msg = f"GRN posted: stock and PO updated ({total:,.2f})."
    if rejected:
        msg += " Some items were rejected at inspection: raise a purchase return."
    return msg


def grn_return(request, grn):
    from procurement.models import PurchaseReturn, PurchaseReturnLine

    require_status(grn, "posted")
    ret = PurchaseReturn.objects.create(receipt=grn)
    for l in grn.lines.all():
        if l.rejected_qty > l.returned_qty:
            PurchaseReturnLine.objects.create(ret=ret, grn_line=l, qty=l.rejected_qty - l.returned_qty, from_rejected=True)
    if not ret.lines.exists():
        ret.reason = "Excess / damaged after acceptance"
        ret.save(update_fields=["reason"])
        return open_edit(request, ret, "No rejected quantities left; add the accepted items to return.")
    return open_detail(request, ret, "Purchase return prepared from rejected quantities.")


def grn_landed_cost(request, grn):
    from procurement.models import LandedCost

    require_status(grn, "posted")
    lc = LandedCost.objects.create(receipt=grn)
    return open_edit(request, lc, "Add freight, duty and other charges to allocate to the received items.")


# --- transfer / return / adjustment / count --------------------------------------

def transfer_post(request, tr):
    if tr.from_warehouse_id == tr.to_warehouse_id:
        raise ValidationError("Choose two different warehouses.")
    for l in tr.lines.select_related("product"):
        out = move_stock(l.product, tr.from_warehouse, -l.qty, date=tr.date, move_type="transfer_out", source=tr)
        move_stock(l.product, tr.to_warehouse, l.qty, out.unit_cost, date=tr.date, move_type="transfer_in", source=tr,
                   bin=l.to_bin)
    set_status(tr, "posted")


def project_return_post(request, ret):
    from .models import StockMove

    journal = []
    total = ZERO
    for l in ret.lines.select_related("product"):
        last_issue = StockMove.objects.filter(product=l.product, project=ret.project, move_type="issue").first()
        cost = last_issue.unit_cost if last_issue else l.product.avg_cost(ret.warehouse)
        move = move_stock(l.product, ret.warehouse, l.qty, cost, date=ret.date, move_type="project_return",
                          source=ret, project=ret.project)
        l.unit_cost, l.value = move.unit_cost, move.value
        l.save(update_fields=["unit_cost", "value"])
        total += move.value
        journal += [
            {"account": stock_account(l.product), "debit": move.value, "description": f"Return {l.product.code}"},
            {"account": expense_account(l.product), "credit": move.value, "project": ret.project,
             "description": f"Surplus returned {l.product.code}"},
        ]
    post_journal(ret.date, journal, "STK", f"Return from project {ret.project.code} ({ret.number})", source=ret)
    ret.total_value = total
    ret.status = "posted"
    ret.save(update_fields=["total_value", "status"])
    return f"Surplus returned to store; project cost reduced by {total:,.2f}."


def adjustment_submit(request, adj):
    if not adj.lines.exists():
        raise ValidationError("Add lines first.")
    if submit_for_approval(adj) is None:
        return adjustment_post(request, adj)


def adjustment_approve(request, adj):
    if approve_step(request, adj, approved_status="pending_approval", rejected_status="rejected"):
        return adjustment_post(request, adj)


def adjustment_post(request, adj):
    journal = []
    total = ZERO
    adj_acc = ctl().require("stock_adjustment")
    for l in adj.lines.select_related("product"):
        cost = l.unit_cost if (l.qty_change > 0 and l.unit_cost) else None
        move = move_stock(l.product, adj.warehouse, l.qty_change, cost, date=adj.date, move_type="adjustment",
                          source=adj)
        l.value = move.value
        l.save(update_fields=["value"])
        total += move.value
        if move.value > 0:
            journal += [{"account": stock_account(l.product), "debit": move.value},
                        {"account": adj_acc, "credit": move.value, "description": adj.get_reason_display()}]
        else:
            journal += [{"account": adj_acc, "debit": -move.value, "description": adj.get_reason_display()},
                        {"account": stock_account(l.product), "credit": -move.value}]
    post_journal(adj.date, journal, "STK", f"Stock adjustment {adj.number} ({adj.get_reason_display()})", source=adj)
    adj.total_value = total
    adj.status = "posted"
    adj.save(update_fields=["total_value", "status"])
    return f"Adjustment posted ({total:,.2f})."


def count_load(request, count):
    from .models import Product, StockCountLine

    existing = set(count.lines.values_list("product_id", flat=True))
    n = 0
    for bal in StockBalance.objects.filter(warehouse=count.warehouse).select_related("product"):
        if bal.product_id not in existing and (bal.qty or count.kind == "physical"):
            StockCountLine.objects.create(count=count, product=bal.product, system_qty=bal.qty, counted_qty=bal.qty)
            n += 1
    return f"{n} item(s) loaded with system quantities. Enter the counted quantities."


def count_complete(request, count):
    lines = list(count.lines.select_related("product"))
    for l in lines:
        l.system_qty = l.product.qty_on_hand(count.warehouse)
        l.save(update_fields=["system_qty"])
    diffs = [l for l in lines if l.difference != 0]
    set_status(count, "completed")
    if not diffs:
        return "Count completed: no differences."
    adj = StockAdjustment.objects.create(warehouse=count.warehouse, reason="count", count=count,
                                         remarks=f"From {count.get_kind_display().lower()} {count.number}")
    for l in diffs:
        StockAdjustmentLine.objects.create(adjustment=adj, product=l.product, qty_change=l.difference)
    return open_detail(request, adj, f"{len(diffs)} difference(s) found. Adjustment {adj.number} created for approval.")


def approve_check(user, obj):
    from core.workflow import can_approve

    return can_approve(user, obj)


__all__ = ["record_decision"]
