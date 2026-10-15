from core.ui import Action, Inline, Related, Screen, register
from core.workflow import can_approve

from . import workflow as wf
from .models import (RFQ, LandedCost, LandedCostCharge, PurchaseOrder, PurchaseOrderLine, PurchaseRequisition,
                     PurchaseRequisitionLine, PurchaseReturn, PurchaseReturnLine, RFQLine, Vendor, VendorQuote,
                     VendorQuoteLine)

M = "procurement"
st = lambda *s: (lambda o: o.status in s)  # noqa: E731


@register(M)
class PRScreen(Screen):
    model = PurchaseRequisition
    slug = "requisitions"
    title = "Purchase Requisitions"
    list_display = ("number", "date", "source", "project", "required_date", "estimated_total", "status")
    search_fields = ("number", "project__name", "cost_centre")
    list_filters = ("status", "source", "project")
    form_fields = ("date", "source", "project", "cost_centre", "required_date", "warehouse", "remarks")
    detail_fields = ("number", "date", "source", "project", "cost_centre", "material_requisition", "required_date",
                     "warehouse", "estimated_total", "status", "remarks")
    inlines = (Inline(PurchaseRequisitionLine, ("product", "description", "qty", "estimated_rate", "required_date"),
                      extra=3, title="Items", display=("product", "description", "qty", "estimated_rate",
                                                         "required_date", "ordered_qty")),)
    actions = (
        Action("submit", "Submit for approval", wf.pr_submit, st("draft")),
        Action("approve", "Approve", wf.pr_approve, st("pending_approval"), style="success", check=can_approve,
               prompt="Comment (optional)"),
        Action("rfq", "+ Create RFQ", wf.pr_rfq, st("approved")),
        Action("po", "Direct PO", wf.pr_direct_po, st("approved"), style="ghost", prompt="Vendor code"),
    )
    related = (
        Related("RFQs", lambda o: o.rfqs.all(), ("number", "date", "status")),
        Related("Purchase orders", lambda o: o.orders.all(), ("number", "date", "vendor", "total", "status")),
    )


@register(M)
class RFQScreen(Screen):
    model = RFQ
    slug = "rfqs"
    title = "RFQs & Quote Comparison"
    list_display = ("number", "date", "requisition", "due_date", "status")
    form_fields = ("date", "requisition", "vendors", "due_date", "remarks")
    inlines = (Inline(RFQLine, ("product", "qty"), extra=2, title="Items"),)
    actions = (Action("send", "Send to vendors", wf.rfq_send, st("draft", "sent")),)
    related = (Related("Vendor quotes", lambda o: o.quotes.all(),
                       ("number", "vendor", "lead_time_days", "payment_terms", "total", "status")),)

    def editable(self, obj):
        return obj.status in ("draft", "sent")


@register(M)
class QuoteScreen(Screen):
    model = VendorQuote
    slug = "vendor-quotes"
    title = "Vendor Quotes"
    list_display = ("number", "date", "rfq", "vendor", "lead_time_days", "total", "status")
    list_filters = ("status", "vendor")
    form_fields = ("date", "rfq", "vendor", "vendor_reference", "lead_time_days", "payment_terms", "delivery_terms",
                   "valid_until", "remarks")
    inlines = (Inline(VendorQuoteLine, ("rfq_line", "rate"), extra=0, title="Prices",
                      display=("rfq_line", "rate", "amount"), totals=("amount",)),)
    actions = (Action("select", "Select vendor → create PO", wf.quote_select, st("draft"), style="success",
                      confirm="Select this vendor and draft the purchase order?"),)


@register(M)
class POScreen(Screen):
    model = PurchaseOrder
    slug = "orders"
    title = "Purchase Orders"
    list_display = ("number", "date", "vendor", "project", "expected_date", "total", "status")
    search_fields = ("number", "vendor__name", "project__name")
    list_filters = ("status", "vendor", "project")
    form_fields = ("date", "vendor", "project", "warehouse", "expected_date", "currency", "exchange_rate",
                   "payment_terms", "delivery_terms", "remarks")
    detail_fields = ("number", "date", "vendor", "project", "requisition", "quote", "warehouse", "expected_date",
                     "currency", "exchange_rate", "payment_terms", "delivery_terms", "subtotal", "vat_amount", "total",
                     "sent_on", ("Last received", "received_on"), "status", "remarks")
    inlines = (Inline(PurchaseOrderLine, ("product", "description", "qty", "rate"), extra=3,
                      display=("product", "description", "qty", "rate", "amount", "received_qty", "returned_qty",
                               "invoiced_qty"), totals=("amount",)),)
    actions = (
        Action("submit", "Submit for approval", wf.po_submit, st("draft", "rejected")),
        Action("approve", "Approve", wf.po_approve, st("pending_approval"), style="success", check=can_approve,
               prompt="Comment (optional)"),
        Action("send", "Mark sent to vendor", wf.po_send, st("approved")),
        Action("receive", "Receive goods (GRN)", wf.po_receive, st("approved", "sent", "partially_received")),
        Action("invoice", "+ Vendor invoice", wf.po_invoice, st("partially_received", "received", "closed"),
               style="ghost", prompt="Vendor invoice number"),
        Action("close", "Close PO", wf.po_close, st("partially_received", "received"), style="ghost"),
        Action("cancel", "Cancel", wf.po_cancel, st("draft", "pending_approval", "approved", "sent"), style="danger",
               confirm="Cancel this purchase order?"),
    )
    related = (
        Related("Goods receipts", lambda o: o.receipts.all(), ("number", "date", "total_value", "status")),
        Related("Vendor invoices", lambda o: o.vendor_invoices.all(), ("number", "vendor_invoice_no", "total", "status")),
    )
    print_template = "print/po.html"

    def editable(self, obj):
        return obj.status in ("draft", "rejected")


@register(M)
class LandedScreen(Screen):
    model = LandedCost
    slug = "landed-costs"
    title = "Landed Costs"
    list_display = ("number", "date", "receipt", "vendor", "total", "status")
    form_fields = ("date", "receipt", "vendor", "remarks")
    inlines = (Inline(LandedCostCharge, ("charge_type", "description", "amount"), extra=3, totals=("amount",)),)
    actions = (Action("post", "Allocate & post", wf.landed_post, st("draft"), style="success"),)


@register(M)
class ReturnScreen(Screen):
    model = PurchaseReturn
    slug = "returns"
    title = "Purchase Returns"
    list_display = ("number", "date", "receipt", "reason", "total_value", "status")
    form_fields = ("date", "receipt", "reason", "remarks")
    inlines = (Inline(PurchaseReturnLine, ("grn_line", "qty", "from_rejected"), extra=1,
                      display=("grn_line__product", "qty", "from_rejected", "value")),)
    actions = (Action("post", "Post return", wf.return_post, st("draft"), style="success"),)
    print_template = "print/purchase_return.html"


@register(M)
class VendorScreen(Screen):
    model = Vendor
    slug = "vendors"
    list_display = ("code", "name", "category", "is_subcontractor", "payment_terms", "active")
    search_fields = ("code", "name", "category")
    list_filters = ("is_subcontractor", "active")
    related = (Related("Purchase orders", lambda o: o.purchaseorder_set.all()[:25],
                       ("number", "date", "total", "status")),)

    def editable(self, obj):
        return True
