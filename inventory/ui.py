from core.ui import Action, Inline, Related, Screen, register

from . import workflow as wf
from .models import (Bin, GoodsReceipt, GoodsReceiptLine, InternalRequest, InternalRequestLine, MaterialRequisition,
                     MaterialRequisitionLine, Product, ProductCategory, ProjectReturn, ProjectReturnLine,
                     StockAdjustment, StockAdjustmentLine, StockCount, StockCountLine, StockIssue, StockIssueLine,
                     StockTransfer, StockTransferLine, UoM, Warehouse)

M = "inventory"
st = lambda *s: (lambda o: o.status in s)  # noqa: E731


@register(M)
class MRScreen(Screen):
    model = MaterialRequisition
    slug = "requisitions"
    title = "Material Requisitions"
    list_display = ("number", "date", "project", "warehouse", "required_date", "is_planning_sheet", "status")
    search_fields = ("number", "project__name", "requested_by")
    list_filters = ("status", "warehouse", "is_planning_sheet")
    form_fields = ("date", "project", "warehouse", "required_date", "requested_by", "is_planning_sheet", "remarks")
    detail_fields = ("number", "date", "project", "warehouse", "required_date", "requested_by", "estimation",
                     "is_planning_sheet", "status", "remarks")
    inlines = (Inline(MaterialRequisitionLine, ("product", "qty", "note"), extra=4, title="Items",
                      display=("product", "qty", "available_at_check", "issued_qty", "purchase_qty", "note")),)
    actions = (
        Action("submit", "Submit", wf.mr_submit, st("draft")),
        Action("check", "Stock check", wf.mr_stock_check, st("submitted", "partially_issued"),
               confirm="Check store availability? Any shortfall raises a purchase requisition."),
        Action("internal", "Internal request (draw from store)", wf.mr_internal_request, st("submitted", "partially_issued")),
        Action("close", "Close", wf.mr_close, st("submitted", "partially_issued", "issued"), style="ghost"),
    )
    related = (
        Related("Internal requests", lambda o: o.internal_requests.all(), ("number", "date", "status")),
        Related("Stock issue vouchers", lambda o: o.issues.all(), ("number", "date", "total_value", "status")),
        Related("Purchase requisitions (shortfall)", lambda o: o.purchase_requisitions.all(),
                ("number", "date", "estimated_total", "status")),
    )


@register(M)
class IRScreen(Screen):
    model = InternalRequest
    slug = "internal-requests"
    title = "Internal Requests"
    list_display = ("number", "date", "requisition", "project", "warehouse", "status")
    form_fields = ("date", "requisition", "project", "warehouse", "remarks")
    inlines = (Inline(InternalRequestLine, ("product", "qty", "bin"), extra=2, title="Items to pick"),)
    actions = (
        Action("release", "Release to store", wf.ir_release, st("draft")),
        Action("issue", "Prepare stock issue", wf.ir_issue, st("draft", "released")),
    )


@register(M)
class SIVScreen(Screen):
    model = StockIssue
    slug = "issues"
    title = "Stock Issue Vouchers"
    list_display = ("number", "date", "project", "warehouse", "total_value", "status")
    search_fields = ("number", "project__name")
    list_filters = ("status", "warehouse", "project")
    form_fields = ("date", "project", "warehouse", "requisition", "issued_to", "remarks")
    inlines = (Inline(StockIssueLine, ("product", "qty", "bin"), extra=3, title="Items issued",
                      display=("product", "qty", "bin", "unit_cost", "value"), totals=("value",)),)
    actions = (Action("post", "Post issue", wf.siv_post, st("draft"), style="success",
                      confirm="Post the issue? Stock is reduced and the cost is charged to the project."),)
    print_template = "print/siv.html"


@register(M)
class GRNScreen(Screen):
    model = GoodsReceipt
    slug = "grn"
    title = "Inspection & GRN"
    help_text = "Create GRNs from a purchase order with 'Receive goods'. Inspect, set accepted / rejected quantities, then post."
    list_display = ("number", "date", "purchase_order", "warehouse", "delivery_note", "total_value", "status")
    search_fields = ("number", "purchase_order__number", "delivery_note")
    list_filters = ("status", "warehouse")
    form_fields = ("date", "purchase_order", "warehouse", "delivery_note", "inspected_by", "remarks")
    inlines = (Inline(GoodsReceiptLine, ("po_line", "product", "received_qty", "accepted_qty", "rejected_qty",
                                         "qc_notes", "bin"), extra=0, title="Received items & QC",
                      display=("product", "received_qty", "accepted_qty", "rejected_qty", "qc_status", "qc_notes",
                               "unit_cost", "value", "returned_qty"), totals=("value",)),)
    actions = (
        Action("post", "Post GRN", wf.grn_post, st("draft"), style="success",
               confirm="Post the GRN? Stock, PO and GRNI are updated."),
        Action("return", "Purchase return", wf.grn_return, st("posted"), style="ghost"),
        Action("landed", "+ Landed cost", wf.grn_landed_cost, st("posted"), style="ghost"),
    )
    related = (
        Related("Purchase returns", lambda o: o.returns.all(), ("number", "date", "total_value", "status")),
        Related("Landed costs", lambda o: o.landed_costs.all(), ("number", "date", "total", "status")),
    )
    can_create = False
    print_template = "print/grn.html"


@register(M)
class TransferScreen(Screen):
    model = StockTransfer
    slug = "transfers"
    title = "Stock Transfers"
    list_display = ("number", "date", "from_warehouse", "to_warehouse", "status")
    form_fields = ("date", "from_warehouse", "to_warehouse", "remarks")
    inlines = (Inline(StockTransferLine, ("product", "qty", "to_bin"), extra=3),)
    actions = (Action("post", "Post transfer", wf.transfer_post, st("draft"), style="success"),)


@register(M)
class ReturnScreen(Screen):
    model = ProjectReturn
    slug = "returns"
    title = "Returns from Project"
    list_display = ("number", "date", "project", "warehouse", "total_value", "status")
    form_fields = ("date", "project", "warehouse", "remarks")
    inlines = (Inline(ProjectReturnLine, ("product", "qty", "condition"), extra=3,
                      display=("product", "qty", "condition", "unit_cost", "value"), totals=("value",)),)
    actions = (Action("post", "Post return", wf.project_return_post, st("draft"), style="success"),)


@register(M)
class AdjustmentScreen(Screen):
    model = StockAdjustment
    slug = "adjustments"
    title = "Stock Adjustments"
    list_display = ("number", "date", "warehouse", "reason", "total_value", "status")
    list_filters = ("status", "reason")
    form_fields = ("date", "warehouse", "reason", "remarks")
    inlines = (Inline(StockAdjustmentLine, ("product", "qty_change", "unit_cost"), extra=3,
                      display=("product", "qty_change", "unit_cost", "value"), totals=("value",)),)
    actions = (
        Action("submit", "Submit for approval", wf.adjustment_submit, st("draft")),
        Action("approve", "Approve & post", wf.adjustment_approve, st("pending_approval"), style="success",
               check=wf.approve_check),
    )


@register(M)
class CountScreen(Screen):
    model = StockCount
    slug = "counts"
    title = "Stock Counts"
    list_display = ("number", "date", "warehouse", "kind", "status")
    form_fields = ("date", "warehouse", "kind", "remarks")
    inlines = (Inline(StockCountLine, ("product", "counted_qty"), extra=2,
                      display=("product", "system_qty", "counted_qty", ("Difference", "difference"))),)
    actions = (
        Action("load", "Load items", wf.count_load, st("draft"), style="ghost"),
        Action("complete", "Complete count", wf.count_complete, st("draft"), style="success",
               confirm="Complete the count? Differences become a stock adjustment for approval."),
    )


class MasterScreen(Screen):
    list_filters = ()

    def editable(self, obj):
        return True


@register(M)
class ProductScreen(MasterScreen):
    model = Product
    slug = "products"
    list_display = ("code", "name", "category", "uom", "is_stock", ("On hand", "qty_on_hand"),
                    "reorder_level", "standard_cost", "active")
    search_fields = ("code", "name")
    list_filters = ("category", "is_stock", "active")
    related = (
        Related("Stock by warehouse", lambda o: o.balances.all(), ("warehouse", "qty", "value", ("Avg cost", "avg_cost"))),
        Related("Recent movements", lambda o: o.moves.all()[:25],
                ("date", "move_type", "warehouse", "bin", "qty", "unit_cost", "value", "project", "reference")),
    )


@register(M)
class CategoryScreen(MasterScreen):
    model = ProductCategory
    slug = "categories"
    title = "Product Categories"
    list_display = ("name", "kind", "parent")
    list_filters = ("kind",)
    search_fields = ("name",)


@register(M)
class WarehouseScreen(MasterScreen):
    model = Warehouse
    slug = "warehouses"
    list_display = ("code", "name", "location", "is_site_store")
    inlines = (Inline(Bin, ("code", "description"), extra=2, title="Bins / locations"),)
    related = (Related("Stock", lambda o: o.stockbalance_set.filter(qty__gt=0).select_related("product"),
                       ("product", "qty", "value")),)


@register(M)
class UoMScreen(MasterScreen):
    model = UoM
    slug = "uom"
    title = "Units of Measure"
    list_display = ("code", "name")
