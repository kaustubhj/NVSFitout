"""Home page: KPIs across modules and the clickable process map from the overview diagram."""
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from .models import ZERO
from .ui import registry

LANES = [
    ("Sales", "sales", [("Lead registration", "leads"), ("Team & site survey", "surveys"), ("Cost estimation", "estimations"),
                        ("BOQ & margin", "boqs"), ("Quotation", "quotations"), ("Approval", "quotations"),
                        ("Client PO / contract", "contracts")]),
    ("Project", "projects", [("New project", "projects"), ("Allocation", "manpower"), ("Variation order", "variations"),
                             ("Project close", "projects")]),
    ("Procurement", "procurement", [("Purchase requisition", "requisitions"), ("RFQ", "rfqs"),
                                    ("Quote comparison", "rfqs"), ("PO & approval", "orders"), ("PO tracking", "orders"),
                                    ("Delivery", "orders")]),
    ("Inventory", "inventory", [("Material requisition", "requisitions"), ("Stock check", "requisitions"),
                                ("Internal request", "internal-requests"), ("Stock issue voucher", "issues"),
                                ("Return / transfer", "transfers"), ("Inspection & GRN", "grn"),
                                ("Purchase return", None)]),
    ("HRMS", "hrms", [("Employee master", "employees"), ("Mobilization", "mobilization"), ("Attendance", "attendance"),
                      ("Overtime", "attendance"), ("Leave & deductions", "leave"), ("Payroll run", "payroll"),
                      ("WPS file", "payroll"), ("Camps & visas", "camps")]),
    ("Accounts", "accounts", [("General ledger", "vouchers"), ("Banking", "banks"), ("Fixed assets", "assets"),
                              ("Receipts & SOA", "receipts"), ("Budgets", "budgets"),
                              ("Progressive invoicing", "invoices"), ("3-way match & AP", "vendor-invoices")]),
]


def process_map(user):
    lanes = []
    for title, mod_key, steps in LANES:
        mod = registry.modules[mod_key]
        if not mod.visible_to(user):
            continue
        items = []
        for label, slug in steps:
            if slug is None:
                url = reverse("erp-list", kwargs={"module": "procurement", "slug": "returns"})
            else:
                url = mod.screens[slug].url()
            items.append((label, url))
        lanes.append({"title": title, "key": mod_key, "steps": items})
    return lanes


def home_context(request):
    from accounts.models import CustomerInvoice, VendorInvoice
    from inventory.models import GoodsReceipt, MaterialRequisition, StockBalance
    from procurement.models import PurchaseOrder, PurchaseRequisition
    from projects.models import Project
    from sales.models import Lead, Quotation
    from hrms.models import Employee, EmployeeDocument

    today = timezone.localdate()
    ar = sum((i.balance for i in CustomerInvoice.objects.filter(status="posted")), ZERO)
    ap = sum((i.balance for i in VendorInvoice.objects.filter(status="posted")), ZERO)
    stock = StockBalance.objects.aggregate(v=Sum("value"))["v"] or ZERO
    kpis = [
        ("Open leads", Lead.objects.filter(status__in=["new", "under_review", "qualified", "estimation"]).count(),
         registry.get("sales", "leads").url()),
        ("Quotes awaiting approval", Quotation.objects.filter(status__in=["pm_approval", "sm_approval"]).count(),
         registry.get("sales", "quotations").url() + "?status=pm_approval"),
        ("Active projects", Project.objects.filter(status="active").count(), registry.get("projects", "projects").url()),
        ("PRs / POs pending approval",
         f"{PurchaseRequisition.objects.filter(status='pending_approval').count()} / "
         f"{PurchaseOrder.objects.filter(status='pending_approval').count()}",
         registry.get("procurement", "orders").url() + "?status=pending_approval"),
        ("Open material requisitions", MaterialRequisition.objects.filter(status__in=["submitted", "partially_issued"]).count(),
         registry.get("inventory", "requisitions").url()),
        ("GRNs under inspection", GoodsReceipt.objects.filter(status="draft").count(), registry.get("inventory", "grn").url()),
        ("Stock value", f"{stock:,.0f}", reverse("inv-valuation")),
        ("Receivables", f"{ar:,.0f}", reverse("acc-ar-ageing")),
        ("Payables", f"{ap:,.0f}", reverse("acc-ap-ageing")),
        ("Active employees", Employee.objects.filter(status="active").count(), registry.get("hrms", "employees").url()),
        ("Documents expiring ≤ 60 days",
         EmployeeDocument.objects.filter(expiry_date__lte=today + timezone.timedelta(days=60),
                                         employee__status="active").count(), reverse("hr-documents")),
    ]
    projects = []
    for p in Project.objects.filter(status="active").order_by("-id")[:8]:
        d = p.profitability()
        used = int(d["total_actual"] / d["total_budget"] * 100) if d["total_budget"] else 0
        projects.append({"p": p, "d": d, "used": used, "bar": min(used, 100)})
    return {"kpis": kpis, "lanes": process_map(request.user), "projects": projects}
