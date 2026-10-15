from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.services import ctl, post_journal
from core.models import ZERO
from core.services import q2, require_status
from core.workflow import approve_step, open_detail, open_edit, set_status, submit_for_approval

from .models import RFQ, PurchaseOrder, PurchaseOrderLine, RFQLine, Vendor, VendorQuote, VendorQuoteLine


# --- purchase requisition -------------------------------------------------------

def pr_submit(request, pr):
    if not pr.lines.exists():
        raise ValidationError("Add at least one item.")
    pr.recalc()
    submit_for_approval(pr)


def pr_approve(request, pr):
    approve_step(request, pr)


def pr_rfq(request, pr):
    rfq = RFQ.objects.create(requisition=pr, due_date=timezone.localdate() + timezone.timedelta(days=5))
    for l in pr.lines.all():
        RFQLine.objects.create(rfq=rfq, pr_line=l, product=l.product, qty=l.qty)
    set_status(pr, "rfq")
    return open_edit(request, rfq, "RFQ created. Choose the vendors to invite.")


def _vendor_from_prompt(request):
    code = (request.action_comment or "").strip()
    vendor = Vendor.objects.filter(code__iexact=code).first() or Vendor.objects.filter(name__icontains=code).first() \
        if code else None
    if vendor is None:
        raise ValidationError(f"No vendor matches '{code}'. Enter a vendor code.")
    return vendor


def pr_direct_po(request, pr):
    vendor = _vendor_from_prompt(request)
    po = _make_po(pr, vendor, None, [(l, l.qty, l.estimated_rate or l.product.standard_cost) for l in pr.lines.all()])
    return open_edit(request, po, "Draft PO created directly from the requisition (no RFQ).")


def _make_po(pr, vendor, quote, items):
    from inventory.models import Warehouse

    warehouse = (pr.warehouse if pr else None) or Warehouse.objects.order_by("id").first()
    po = PurchaseOrder.objects.create(
        vendor=vendor, project=pr.project if pr else None, requisition=pr, quote=quote, warehouse=warehouse,
        currency=vendor.currency, exchange_rate=vendor.currency.rate if vendor.currency else 1,
        payment_terms=(quote.payment_terms if quote and quote.payment_terms else vendor.payment_terms),
        delivery_terms=quote.delivery_terms if quote else "",
        expected_date=(timezone.localdate() + timezone.timedelta(days=quote.lead_time_days)) if quote else None,
    )
    for pr_line, qty, rate in items:
        PurchaseOrderLine.objects.create(order=po, pr_line=pr_line, product=pr_line.product, qty=qty, rate=rate,
                                         description=pr_line.description)
        pr_line.ordered_qty += qty
        pr_line.save(update_fields=["ordered_qty"])
    po.recalc()
    if pr:
        set_status(pr, "ordered")
    return po


# --- RFQ -----------------------------------------------------------------------

def rfq_send(request, rfq):
    if not rfq.vendors.exists():
        raise ValidationError("Select at least one vendor.")
    set_status(rfq, "sent")
    for v in rfq.vendors.all():
        if not rfq.quotes.filter(vendor=v).exists():
            q = VendorQuote.objects.create(rfq=rfq, vendor=v, payment_terms=v.payment_terms)
            for l in rfq.lines.all():
                VendorQuoteLine.objects.create(quote=q, rfq_line=l, rate=ZERO)
    return "RFQ sent. A quote sheet was opened for each vendor: enter their prices, lead time and terms."


def quote_select(request, quote):
    rfq = quote.rfq
    if rfq.status == "closed":
        raise ValidationError("A vendor was already selected for this RFQ.")
    if not any(l.rate for l in quote.lines.all()):
        raise ValidationError("This quote has no prices.")
    rfq.quotes.exclude(pk=quote.pk).update(status="not_selected")
    set_status(quote, "selected")
    set_status(rfq, "closed")
    items = []
    for ql in quote.lines.select_related("rfq_line__pr_line", "rfq_line__product"):
        if ql.rate and ql.rfq_line.pr_line:
            items.append((ql.rfq_line.pr_line, ql.rfq_line.qty, ql.rate))
    po = _make_po(rfq.requisition, quote.vendor, quote, items)
    return open_detail(request, po, f"{quote.vendor.name} selected. Purchase order {po.number} drafted.")


# --- purchase order -------------------------------------------------------------

def po_submit(request, po):
    if not po.lines.exists():
        raise ValidationError("Add at least one line.")
    po.recalc()
    submit_for_approval(po)


def po_approve(request, po):
    approve_step(request, po)


def po_send(request, po):
    po.status = "sent"
    po.sent_on = timezone.localdate()
    po.save(update_fields=["status", "sent_on"])


def po_receive(request, po):
    from inventory.models import GoodsReceipt, GoodsReceiptLine

    pending = [l for l in po.lines.select_related("product") if l.pending_qty > 0]
    if not pending:
        raise ValidationError("Everything on this PO has been received.")
    grn = GoodsReceipt.objects.create(purchase_order=po, warehouse=po.warehouse)
    for l in pending:
        GoodsReceiptLine.objects.create(receipt=grn, po_line=l, product=l.product, received_qty=l.pending_qty,
                                        accepted_qty=l.pending_qty, bin=l.product.default_bin)
    return open_edit(request, grn, "GRN drafted with the pending quantities. Record the inspection result, then post.")


def po_invoice(request, po):
    from accounts.models import VendorInvoice, VendorInvoiceLine

    inv = VendorInvoice.objects.create(vendor=po.vendor, purchase_order=po, project=po.project,
                                       vendor_invoice_no=request.action_comment or "", currency=po.currency,
                                       exchange_rate=po.exchange_rate)
    for l in po.lines.all():
        qty = l.received_qty - l.invoiced_qty
        if qty > 0:
            VendorInvoiceLine.objects.create(invoice=inv, po_line=l, description=str(l.product), qty=qty, rate=l.rate)
    inv.recalc()
    return open_edit(request, inv, "Vendor invoice drafted from received quantities. Enter the vendor's figures, then run the 3-way match.")


def po_close(request, po):
    set_status(po, "closed")


def po_cancel(request, po):
    if any(l.received_qty for l in po.lines.all()):
        raise ValidationError("Goods were already received; close the PO instead.")
    set_status(po, "cancelled")


# --- landed cost / purchase return -------------------------------------------------

def landed_post(request, lc):
    from inventory.services import revalue_stock, stock_account

    require_status(lc, "draft")
    lc.recalc()
    if not lc.total:
        raise ValidationError("Add charges first.")
    grn = lc.receipt
    lines = [l for l in grn.lines.select_related("product") if l.product.is_stock and l.value]
    base = sum((l.value for l in lines), ZERO)
    if not base:
        raise ValidationError("The GRN has no stock value to allocate to.")
    journal = []
    remaining = lc.total
    for i, l in enumerate(lines):
        share = remaining if i == len(lines) - 1 else q2(lc.total * l.value / base)
        remaining -= share
        revalue_stock(l.product, grn.warehouse, share, date=lc.date, source=lc, reference=lc.number)
        journal.append({"account": stock_account(l.product), "debit": share, "description": f"Landed cost {l.product.code}"})
    credit = {"account": ctl().require("payable") if lc.vendor else ctl().require("landed_cost_clearing"),
              "credit": lc.total, "vendor": lc.vendor, "description": f"Landed cost {grn.number}"}
    post_journal(lc.date, journal + [credit], "STK", f"Landed cost {lc.number} on {grn.number}", source=lc)
    grn.landed_cost_total += lc.total
    grn.save(update_fields=["landed_cost_total"])
    set_status(lc, "posted")
    return f"{lc.total:,.2f} allocated across {len(lines)} item(s) by value."


def return_post(request, ret):
    from inventory.services import move_stock, stock_account

    require_status(ret, "draft")
    grn = ret.receipt
    po = grn.purchase_order
    journal = []
    total = ZERO
    for l in ret.lines.select_related("grn_line__product", "grn_line__po_line"):
        gl = l.grn_line
        if l.from_rejected:
            if l.qty > gl.rejected_qty - gl.returned_qty:
                raise ValidationError(f"{gl.product.code}: only {gl.rejected_qty - gl.returned_qty:g} rejected qty left to return.")
            l.value = ZERO
        else:
            if gl.product.is_stock:
                move = move_stock(gl.product, grn.warehouse, -l.qty, date=ret.date, move_type="purchase_return",
                                  source=ret)
                l.value = -move.value
                credit_acc = stock_account(gl.product)
            else:
                from inventory.services import expense_account

                l.value = q2(gl.unit_cost * l.qty)
                credit_acc = expense_account(gl.product)
            journal += [
                {"account": ctl().require("grni"), "debit": l.value, "vendor": po.vendor, "description": f"Return {gl.product.code}"},
                {"account": credit_acc, "credit": l.value, "project": po.project if not gl.product.is_stock else None},
            ]
            gl.po_line.received_qty -= l.qty
            gl.po_line.returned_qty += l.qty
            gl.po_line.save(update_fields=["received_qty", "returned_qty"])
        l.save(update_fields=["value"])
        gl.returned_qty += l.qty
        gl.save(update_fields=["returned_qty"])
        total += l.value
    if journal:
        post_journal(ret.date, journal, "STK", f"Purchase return {ret.number} to {po.vendor.name}", source=ret)
        po.update_receipt_status()
    ret.total_value = total
    ret.status = "posted"
    ret.save(update_fields=["total_value", "status"])
    return "Purchase return posted."
