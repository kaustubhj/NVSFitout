from django.core.exceptions import ValidationError
from django.utils import timezone

from core.ui import Action, Inline, Related, Screen, register
from core.workflow import approve_step, can_approve, open_edit, set_status, submit_for_approval

from .models import ManpowerAllocation, Project, ProjectTask, VariationLine, VariationOrder

M = "projects"
st = lambda *s: (lambda o: o.status in s)  # noqa: E731


def project_hold(request, p):
    set_status(p, "on_hold")


def project_resume(request, p):
    set_status(p, "active")


def project_complete(request, p):
    set_status(p, "completed")


def project_close(request, p):
    data = p.profitability()
    p.close_summary = {
        "revenue": str(data["revenue"]), "direct_cost": str(data["direct_cost"]), "overhead": str(data["overhead"]),
        "gp": str(data["gp"]), "np": str(data["np"]), "gp_percent": str(data["gp_percent"]),
        "np_percent": str(data["np_percent"]),
        "budget": {k: str(v) for k, v in data["budget"].items()},
        "actual": {k: str(v) for k, v in data["actual"].items()},
    }
    p.closed_on = timezone.localdate()
    p.status = "closed"
    p.save()
    return f"Project closed. GP {data['gp']:,.2f} ({data['gp_percent']}%), NP {data['np']:,.2f} ({data['np_percent']}%)."


def project_mr(request, p):
    from inventory.models import MaterialRequisition, Warehouse

    wh = Warehouse.objects.filter(is_site_store=False).first() or Warehouse.objects.first()
    mr = MaterialRequisition.objects.create(project=p, warehouse=wh, requested_by=str(request.user))
    return open_edit(request, mr, "Material requisition created for the project.")


def project_vo(request, p):
    vo = VariationOrder.objects.create(project=p, title="Variation")
    return open_edit(request, vo)


def vo_submit(request, vo):
    if not vo.lines.exists():
        raise ValidationError("Add the changed BOQ lines first.")
    submit_for_approval(vo, pending_status="submitted")


def vo_approve(request, vo):
    if approve_step(request, vo, approved_status="approved", rejected_status="draft"):
        return f"VO approved: contract value +{vo.selling_total:,.2f}, budget +{vo.cost_total:,.2f}. Work may proceed."


@register(M)
class ProjectScreen(Screen):
    model = Project
    slug = "projects"
    list_display = ("code", "name", "customer", "manager", "contract_value", ("Revised value", "revised_contract_value"),
                    "progress_percent", "status")
    search_fields = ("code", "name", "customer__name", "location")
    list_filters = ("status", "manager")
    form_fields = ("code", "name", "customer", "quotation", "contract", "manager", "location", "start_date", "end_date",
                   "contract_value", "budget_material", "budget_labour", "budget_subcontract", "budget_overhead",
                   "progress_percent")
    detail_fields = ("code", "name", "customer", "quotation", "contract", "manager", "location", "start_date",
                     "end_date", "contract_value", ("Revised contract value", "revised_contract_value"),
                     "progress_percent", "status", "closed_on")
    inlines = (
        Inline(ProjectTask, ("name", "responsible", "start_date", "end_date", "percent_complete", "status"), extra=1,
               title="Tasks"),
        Inline(ManpowerAllocation, ("employee", "trade", "role", "date_from", "date_to"), extra=1,
               title="Manpower allocation (direct & hired)"),
    )
    actions = (
        Action("mr", "+ Material requisition", project_mr, st("active")),
        Action("vo", "+ Variation order", project_vo, st("active", "on_hold")),
        Action("hold", "Put on hold", project_hold, st("active"), style="ghost"),
        Action("resume", "Resume", project_resume, st("on_hold", "completed"), style="ghost"),
        Action("complete", "Mark completed", project_complete, st("active")),
        Action("close", "Close project", project_close, st("completed"), style="danger",
               groups=["Senior Manager", "Accounts"],
               confirm="Close the project? Budget vs actual, GP and NP are frozen."),
    )
    related = (
        Related("Variation orders", lambda o: o.variations.all(), ("number", "date", "title", "cost_total", "selling_total", "status")),
        Related("Material requisitions", lambda o: o.materialrequisition_set.all()[:30], ("number", "date", "warehouse", "status")),
        Related("Stock issues", lambda o: o.stockissue_set.all()[:30], ("number", "date", "warehouse", "total_value", "status")),
        Related("Purchase orders", lambda o: o.purchaseorder_set.all()[:30], ("number", "date", "vendor", "total", "status")),
        Related("Customer invoices", lambda o: o.customer_invoices.all(), ("number", "date", "invoice_type", "gross_amount", "total", "status")),
    )

    def editable(self, obj):
        return obj.status != "closed"

    def deletable(self, obj):
        return False


@register(M)
class VariationScreen(Screen):
    model = VariationOrder
    slug = "variations"
    title = "Variation Orders"
    list_display = ("number", "date", "project", "title", "cost_total", "selling_total", "status")
    search_fields = ("number", "title", "project__name")
    form_fields = ("date", "project", "title", "client_reference", "reason", "remarks")
    inlines = (Inline(VariationLine, ("category", "description", "qty", "uom", "unit_cost", "selling_rate"), extra=2,
                      title="Changed BOQ lines",
                      display=("category", "description", "qty", "uom", "unit_cost", "cost_amount", "selling_rate",
                               "selling_amount"), totals=("cost_amount", "selling_amount")),)
    actions = (
        Action("submit", "Submit for BOQ re-approval", vo_submit, st("draft")),
        Action("approve", "Re-approve BOQ / VO", vo_approve, st("submitted"), style="success", check=can_approve,
               prompt="Comment (optional)"),
    )


@register(M)
class TaskScreen(Screen):
    model = ProjectTask
    slug = "tasks"
    list_display = ("project", "name", "responsible", "start_date", "end_date", "percent_complete", "status")
    search_fields = ("name", "project__name")
    list_filters = ("status",)

    def editable(self, obj):
        return True


@register(M)
class ManpowerScreen(Screen):
    model = ManpowerAllocation
    slug = "manpower"
    title = "Manpower Allocation"
    list_display = ("project", "employee", "trade", "role", "date_from", "date_to")
    search_fields = ("employee__name", "project__name")
    list_filters = ("project",)
