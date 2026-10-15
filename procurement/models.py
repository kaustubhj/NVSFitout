from decimal import Decimal

from django.db import models
from django.db.models import Sum

from core.models import ZERO, Doc, money_field, qty_field
from core.services import q2


class Vendor(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=80, blank=True, help_text="e.g. Joinery, MEP, Gypsum, Flooring")
    is_subcontractor = models.BooleanField(default=False)
    trn = models.CharField("TRN", max_length=30, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    payment_terms = models.CharField(max_length=100, default="30 days")
    credit_days = models.PositiveIntegerField(default=30)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    bank_details = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} · {self.name}"


class PurchaseRequisition(Doc):
    SEQ_KEY, SEQ_PREFIX = "PR", "PR-"
    APPROVAL_DOC_TYPE = "purchase_requisition"
    SOURCES = [("site", "Site / material requisition"), ("replenishment", "Replenishment (reorder level)"),
               ("manual", "Manual")]
    STATUS = [("draft", "Draft"), ("pending_approval", "Pending approval"), ("approved", "Approved"),
              ("rfq", "RFQ issued"), ("ordered", "Ordered"), ("rejected", "Rejected"), ("cancelled", "Cancelled")]
    source = models.CharField(max_length=20, choices=SOURCES, default="manual")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    cost_centre = models.CharField(max_length=60, blank=True)
    material_requisition = models.ForeignKey("inventory.MaterialRequisition", null=True, blank=True,
                                             on_delete=models.SET_NULL, related_name="purchase_requisitions")
    required_date = models.DateField(null=True, blank=True)
    warehouse = models.ForeignKey("inventory.Warehouse", null=True, blank=True, on_delete=models.PROTECT,
                                  help_text="Deliver to")
    estimated_total = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def approval_amount(self):
        return self.estimated_total

    def recalc(self):
        total = ZERO
        for l in self.lines.select_related("product"):
            total += q2(l.qty * (l.estimated_rate or l.product.standard_cost))
        self.estimated_total = total
        self.save(update_fields=["estimated_total"])


class PurchaseRequisitionLine(models.Model):
    requisition = models.ForeignKey(PurchaseRequisition, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    description = models.CharField(max_length=200, blank=True)
    qty = qty_field()
    estimated_rate = money_field()
    required_date = models.DateField(null=True, blank=True)
    ordered_qty = qty_field(editable=False)


class RFQ(Doc):
    SEQ_KEY, SEQ_PREFIX = "RFQ", "RFQ-"
    STATUS = [("draft", "Draft"), ("sent", "Sent to vendors"), ("closed", "Vendor selected"), ("cancelled", "Cancelled")]
    requisition = models.ForeignKey(PurchaseRequisition, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="rfqs")
    vendors = models.ManyToManyField(Vendor)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "RFQ"
        verbose_name_plural = "RFQs"
        ordering = ["-id"]

    @property
    def detail_panel(self):
        from django.template.loader import render_to_string

        return render_to_string("procurement/comparison.html", {"rfq": self, "cmp": self.comparison()})

    def comparison(self):
        quotes = list(self.quotes.prefetch_related("lines").select_related("vendor"))
        rows = []
        for line in self.lines.select_related("product"):
            cells = []
            prices = []
            for q in quotes:
                ql = next((x for x in q.lines.all() if x.rfq_line_id == line.id), None)
                cells.append(ql)
                if ql and ql.rate:
                    prices.append(ql.rate)
            best = min(prices) if prices else None
            rows.append({"line": line, "cells": [{"q": c, "best": c is not None and c.rate == best} for c in cells]})
        return {"quotes": quotes, "rows": rows}


class RFQLine(models.Model):
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="lines")
    pr_line = models.ForeignKey(PurchaseRequisitionLine, null=True, blank=True, on_delete=models.SET_NULL)
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    qty = qty_field()

    def __str__(self):
        return f"{self.product} × {self.qty}"


class VendorQuote(Doc):
    SEQ_KEY, SEQ_PREFIX = "VQ", "VQ-"
    STATUS = [("draft", "Received"), ("selected", "Selected"), ("not_selected", "Not selected")]
    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="quotes")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    vendor_reference = models.CharField(max_length=60, blank=True)
    lead_time_days = models.PositiveIntegerField(default=7)
    payment_terms = models.CharField(max_length=100, blank=True)
    delivery_terms = models.CharField(max_length=100, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    total = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def __str__(self):
        return f"{self.number} · {self.vendor.name}"

    def recalc(self):
        self.total = self.lines.aggregate(t=Sum("amount"))["t"] or ZERO
        self.save(update_fields=["total"])


class VendorQuoteLine(models.Model):
    quote = models.ForeignKey(VendorQuote, on_delete=models.CASCADE, related_name="lines")
    rfq_line = models.ForeignKey(RFQLine, on_delete=models.CASCADE)
    rate = money_field()
    amount = money_field(editable=False)

    def save(self, *args, **kwargs):
        self.amount = q2(self.rfq_line.qty * self.rate)
        super().save(*args, **kwargs)


class PurchaseOrder(Doc):
    SEQ_KEY, SEQ_PREFIX = "PO", "PO-"
    APPROVAL_DOC_TYPE = "purchase_order"
    STATUS = [("draft", "Draft"), ("pending_approval", "Pending approval"), ("approved", "Approved"),
              ("sent", "Sent to vendor"), ("partially_received", "Partially received"),
              ("received", "Fully received"), ("closed", "Closed"), ("cancelled", "Cancelled"),
              ("rejected", "Rejected")]
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    requisition = models.ForeignKey(PurchaseRequisition, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="orders")
    quote = models.ForeignKey(VendorQuote, null=True, blank=True, on_delete=models.SET_NULL)
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT, help_text="Deliver to")
    expected_date = models.DateField(null=True, blank=True)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1"))
    payment_terms = models.CharField(max_length=100, blank=True)
    delivery_terms = models.CharField(max_length=100, blank=True)
    subtotal = money_field(editable=False)
    vat_amount = money_field(editable=False)
    total = money_field(editable=False)
    sent_on = models.DateField(null=True, blank=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def approval_amount(self):
        return self.subtotal * self.exchange_rate

    def recalc(self):
        from core.models import Company

        if self.currency and self.exchange_rate == 1 and self.currency.rate != 1:
            self.exchange_rate = self.currency.rate
        self.subtotal = self.lines.aggregate(t=Sum("amount"))["t"] or ZERO
        self.vat_amount = q2(self.subtotal * Company.get().vat_percent / 100)
        self.total = self.subtotal + self.vat_amount
        self.save(update_fields=["subtotal", "vat_amount", "total", "exchange_rate"])

    def update_receipt_status(self):
        lines = list(self.lines.all())
        if lines and all(l.received_qty >= l.qty for l in lines):
            self.status = "received"
        elif any(l.received_qty > 0 for l in lines):
            self.status = "partially_received"
        self.save(update_fields=["status"])

    @property
    def received_on(self):
        last = self.receipts.filter(status="posted").order_by("-date").first()
        return last.date if last else None


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    pr_line = models.ForeignKey(PurchaseRequisitionLine, null=True, blank=True, on_delete=models.SET_NULL)
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    description = models.CharField(max_length=200, blank=True)
    qty = qty_field()
    rate = money_field(decimal_places=4)
    amount = money_field(editable=False)
    received_qty = qty_field(editable=False)
    returned_qty = qty_field(editable=False)
    invoiced_qty = qty_field(editable=False)

    def save(self, *args, **kwargs):
        self.amount = q2(self.qty * self.rate)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.number} · {self.product.code} × {self.qty:g}"

    @property
    def pending_qty(self):
        return max(self.qty - self.received_qty, ZERO)


class LandedCost(Doc):
    SEQ_KEY, SEQ_PREFIX = "LC", "LC-"
    STATUS = [("draft", "Draft"), ("posted", "Posted")]
    receipt = models.ForeignKey("inventory.GoodsReceipt", on_delete=models.PROTECT, related_name="landed_costs")
    vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.PROTECT,
                               help_text="Freight forwarder / customs agent (credited to AP); blank = clearing account")
    total = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def recalc(self):
        self.total = self.charges.aggregate(t=Sum("amount"))["t"] or ZERO
        self.save(update_fields=["total"])


class LandedCostCharge(models.Model):
    TYPES = [("freight", "Freight"), ("duty", "Customs duty"), ("clearing", "Clearing & handling"),
             ("insurance", "Insurance"), ("other", "Other")]
    landed_cost = models.ForeignKey(LandedCost, on_delete=models.CASCADE, related_name="charges")
    charge_type = models.CharField(max_length=20, choices=TYPES, default="freight")
    description = models.CharField(max_length=200, blank=True)
    amount = money_field()


class PurchaseReturn(Doc):
    SEQ_KEY, SEQ_PREFIX = "PRN", "PRN-"
    STATUS = [("draft", "Draft"), ("posted", "Posted")]
    receipt = models.ForeignKey("inventory.GoodsReceipt", on_delete=models.PROTECT, related_name="returns")
    reason = models.CharField(max_length=200, default="Rejected at inspection")
    total_value = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")


class PurchaseReturnLine(models.Model):
    ret = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name="lines")
    grn_line = models.ForeignKey("inventory.GoodsReceiptLine", on_delete=models.PROTECT)
    qty = qty_field()
    from_rejected = models.BooleanField(default=True, help_text="Rejected goods were never taken into stock")
    value = money_field(editable=False)
