from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Sum

from core.models import ZERO, Doc, money_field, qty_field, today


class Warehouse(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=200, blank=True)
    is_site_store = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.code} · {self.name}"


class Bin(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="bins")
    code = models.CharField(max_length=20)
    description = models.CharField(max_length=100, blank=True)

    class Meta:
        unique_together = [("warehouse", "code")]

    def __str__(self):
        return f"{self.warehouse.code}/{self.code}"


class UoM(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=40)

    class Meta:
        verbose_name = "unit of measure"

    def __str__(self):
        return self.code


class ProductCategory(models.Model):
    KINDS = [("material", "Material type"), ("trade", "Trade"), ("usage", "Usage")]
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=KINDS, default="material")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name_plural = "product categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT)
    trade_category = models.ForeignKey(ProductCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                       limit_choices_to={"kind": "trade"})
    uom = models.ForeignKey(UoM, on_delete=models.PROTECT, verbose_name="UoM")
    is_stock = models.BooleanField("Stock item", default=True, help_text="Untick for services / subcontract work")
    standard_cost = money_field()
    reorder_level = qty_field()
    reorder_qty = qty_field()
    default_bin = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)
    stock_account = models.ForeignKey("accounts.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cogs_account = models.ForeignKey("accounts.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                     verbose_name="COGS account")
    expense_account = models.ForeignKey("accounts.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                        help_text="Project cost account when issued / received for a project")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    def qty_on_hand(self, warehouse=None):
        qs = self.balances.all()
        if warehouse:
            qs = qs.filter(warehouse=warehouse)
        return qs.aggregate(q=Sum("qty"))["q"] or ZERO

    def avg_cost(self, warehouse=None):
        qs = self.balances.all()
        if warehouse:
            qs = qs.filter(warehouse=warehouse)
        agg = qs.aggregate(q=Sum("qty"), v=Sum("value"))
        if agg["q"]:
            return agg["v"] / agg["q"]
        return self.standard_cost

    def reserved_qty(self):
        agg = MaterialRequisitionLine.objects.filter(
            product=self, requisition__status__in=["submitted", "partially_issued"]).aggregate(
            q=Sum("qty"), i=Sum("issued_qty"))
        return (agg["q"] or ZERO) - (agg["i"] or ZERO)

    def on_order_qty(self):
        from procurement.models import PurchaseOrderLine

        agg = PurchaseOrderLine.objects.filter(
            product=self, order__status__in=["approved", "sent", "partially_received"]).aggregate(
            q=Sum("qty"), r=Sum("received_qty"))
        return (agg["q"] or ZERO) - (agg["r"] or ZERO)


class StockBalance(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="balances")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    qty = qty_field()
    value = money_field()

    class Meta:
        unique_together = [("product", "warehouse")]

    @property
    def avg_cost(self):
        return (self.value / self.qty) if self.qty else ZERO


class StockMove(models.Model):
    date = models.DateField(default=today)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="moves")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    bin = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)
    qty = qty_field(help_text="Positive = in, negative = out")
    unit_cost = money_field(decimal_places=4)
    value = money_field()
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    move_type = models.CharField(max_length=20)
    content_type = models.ForeignKey(ContentType, null=True, on_delete=models.SET_NULL)
    object_id = models.PositiveBigIntegerField(null=True)
    source = GenericForeignKey("content_type", "object_id")
    reference = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


# --- documents --------------------------------------------------------------

class MaterialRequisition(Doc):
    SEQ_KEY, SEQ_PREFIX = "MR", "MR-"
    STATUS = [("draft", "Draft"), ("submitted", "Submitted"), ("partially_issued", "Partially issued"),
              ("issued", "Issued"), ("closed", "Closed"), ("cancelled", "Cancelled")]
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    estimation = models.ForeignKey("sales.Estimation", null=True, blank=True, on_delete=models.SET_NULL,
                                   help_text="Set when the store receives an estimation sheet for planning")
    is_planning_sheet = models.BooleanField("Estimation sheet (planning only, no prices)", default=False)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    required_date = models.DateField(null=True, blank=True)
    requested_by = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def update_status(self):
        lines = list(self.lines.all())
        if lines and all(l.issued_qty >= l.qty for l in lines):
            self.status = "issued"
        elif any(l.issued_qty > 0 for l in lines):
            self.status = "partially_issued"
        self.save(update_fields=["status"])


class MaterialRequisitionLine(models.Model):
    requisition = models.ForeignKey(MaterialRequisition, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = qty_field()
    issued_qty = qty_field(editable=False)
    purchase_qty = qty_field("Sent to purchase", editable=False)
    available_at_check = qty_field("Available (last check)", editable=False)
    note = models.CharField(max_length=200, blank=True)

    @property
    def pending_qty(self):
        return max(self.qty - self.issued_qty, ZERO)


class InternalRequest(Doc):
    SEQ_KEY, SEQ_PREFIX = "IR", "IR-"
    STATUS = [("draft", "Draft"), ("released", "Released to store"), ("issued", "Issued"), ("cancelled", "Cancelled")]
    requisition = models.ForeignKey(MaterialRequisition, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="internal_requests")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")


class InternalRequestLine(models.Model):
    request = models.ForeignKey(InternalRequest, on_delete=models.CASCADE, related_name="lines")
    mr_line = models.ForeignKey(MaterialRequisitionLine, null=True, blank=True, on_delete=models.SET_NULL)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = qty_field()
    bin = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)


class StockIssue(Doc):
    SEQ_KEY, SEQ_PREFIX = "SIV", "SIV-"
    STATUS = [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")]
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    requisition = models.ForeignKey(MaterialRequisition, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="issues")
    internal_request = models.ForeignKey(InternalRequest, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="issues")
    issued_to = models.CharField(max_length=100, blank=True)
    total_value = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "stock issue voucher"
        ordering = ["-id"]


class StockIssueLine(models.Model):
    issue = models.ForeignKey(StockIssue, on_delete=models.CASCADE, related_name="lines")
    mr_line = models.ForeignKey(MaterialRequisitionLine, null=True, blank=True, on_delete=models.SET_NULL)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = qty_field()
    bin = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)
    unit_cost = money_field(decimal_places=4, editable=False)
    value = money_field(editable=False)


class GoodsReceipt(Doc):
    SEQ_KEY, SEQ_PREFIX = "GRN", "GRN-"
    STATUS = [("draft", "Draft / under inspection"), ("posted", "Posted"), ("cancelled", "Cancelled")]
    purchase_order = models.ForeignKey("procurement.PurchaseOrder", on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    delivery_note = models.CharField("Vendor delivery note", max_length=60, blank=True)
    inspected_by = models.CharField(max_length=100, blank=True)
    total_value = money_field(editable=False)
    landed_cost_total = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "goods receipt (GRN)"
        verbose_name_plural = "goods receipts (GRN)"
        ordering = ["-id"]


class GoodsReceiptLine(models.Model):
    QC = [("pending", "Pending"), ("passed", "Passed"), ("partial", "Partly rejected"), ("failed", "Rejected")]
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    po_line = models.ForeignKey("procurement.PurchaseOrderLine", on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    received_qty = qty_field()
    accepted_qty = qty_field()
    rejected_qty = qty_field()
    qc_status = models.CharField("QC", max_length=10, choices=QC, default="passed")
    qc_notes = models.CharField("QC notes", max_length=200, blank=True)
    bin = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)
    unit_cost = money_field(decimal_places=4, editable=False)
    value = money_field(editable=False)
    returned_qty = qty_field(editable=False)


class StockTransfer(Doc):
    SEQ_KEY, SEQ_PREFIX = "STR", "TR-"
    STATUS = [("draft", "Draft"), ("posted", "Posted")]
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=STATUS, default="draft")


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = qty_field()
    to_bin = models.ForeignKey(Bin, null=True, blank=True, on_delete=models.SET_NULL)


class ProjectReturn(Doc):
    SEQ_KEY, SEQ_PREFIX = "PRT", "RT-"
    STATUS = [("draft", "Draft"), ("posted", "Posted")]
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    total_value = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "return from project"
        verbose_name_plural = "returns from project"
        ordering = ["-id"]


class ProjectReturnLine(models.Model):
    ret = models.ForeignKey(ProjectReturn, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = qty_field()
    condition = models.CharField(max_length=60, blank=True)
    unit_cost = money_field(decimal_places=4, editable=False)
    value = money_field(editable=False)


class StockAdjustment(Doc):
    SEQ_KEY, SEQ_PREFIX = "ADJ", "ADJ-"
    APPROVAL_DOC_TYPE = "stock_adjustment"
    REASONS = [("count", "Physical count difference"), ("damage", "Damaged"), ("expiry", "Expired / obsolete"),
               ("theft", "Loss / theft"), ("opening", "Opening balance"), ("other", "Other")]
    STATUS = [("draft", "Draft"), ("pending_approval", "Pending approval"), ("posted", "Posted"), ("rejected", "Rejected")]
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    reason = models.CharField(max_length=20, choices=REASONS, default="count")
    count = models.ForeignKey("StockCount", null=True, blank=True, on_delete=models.SET_NULL)
    total_value = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def approval_amount(self):
        return abs(sum(((l.qty_change * (l.unit_cost or l.product.avg_cost(self.warehouse)))
                        for l in self.lines.all()), ZERO))


class StockAdjustmentLine(models.Model):
    adjustment = models.ForeignKey(StockAdjustment, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty_change = qty_field(help_text="+ to add, − to remove")
    unit_cost = money_field(decimal_places=4, help_text="For additions; blank uses average cost")
    value = money_field(editable=False)


class StockCount(Doc):
    SEQ_KEY, SEQ_PREFIX = "CNT", "SC-"
    KINDS = [("physical", "Full physical count"), ("cycle", "Cycle count")]
    STATUS = [("draft", "Counting"), ("completed", "Completed")]
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=KINDS, default="cycle")
    status = models.CharField(max_length=20, choices=STATUS, default="draft")


class StockCountLine(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    system_qty = qty_field(editable=False)
    counted_qty = qty_field()

    @property
    def difference(self):
        return self.counted_qty - self.system_qty
