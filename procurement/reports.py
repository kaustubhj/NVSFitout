from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from core.models import ZERO
from core.reports import DateRangeForm, Table, render_report, total_row
from core.ui import registry

from .models import PurchaseOrder, PurchaseRequisition

LIVE = ["approved", "sent", "partially_received", "received", "closed"]


def _orders(request, form):
    qs = PurchaseOrder.objects.filter(status__in=LIVE).select_related("vendor", "project")
    if form.is_valid():
        if form.cleaned_data["date_from"]:
            qs = qs.filter(date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data["date_to"]:
            qs = qs.filter(date__lte=form.cleaned_data["date_to"])
    return qs


def by_project(request):
    form = DateRangeForm(request.GET or None)
    data = defaultdict(lambda: {"pr": 0, "pr_open": 0, "po": 0, "po_open": 0, "spend": ZERO, "received": ZERO})
    for pr in PurchaseRequisition.objects.select_related("project"):
        key = pr.project.code if pr.project else "(no project)"
        data[key]["pr"] += 1
        if pr.status in ("draft", "pending_approval", "approved", "rfq"):
            data[key]["pr_open"] += 1
    for po in _orders(request, form):
        key = po.project.code if po.project else "(no project)"
        data[key]["po"] += 1
        if po.status in ("approved", "sent", "partially_received"):
            data[key]["po_open"] += 1
        data[key]["spend"] += po.subtotal * po.exchange_rate
        for l in po.lines.all():
            data[key]["received"] += l.received_qty * l.rate * po.exchange_rate
    rows = [[k, v["pr"], v["pr_open"], v["po"], v["po_open"], v["spend"], round(v["received"], 2)]
            for k, v in sorted(data.items())]
    detail = [[po.project.code if po.project else "", po.number, po.date, po.vendor.name, po.get_status_display(),
               po.total] for po in PurchaseOrder.objects.select_related("project", "vendor").order_by("project__code", "-date")[:500]]
    return render_report(request, "Requisitions & orders by project", [
        Table("Summary", ["Project", "PRs", "Open PRs", "POs", "Open POs", "PO value (excl. VAT)", "Received value"],
              rows, total_row(rows, [5, 6])),
        Table("Purchase orders", ["Project", "PO", "Date", "Vendor", "Status", "Total"], detail),
    ], form)


def analytics(request):
    form = DateRangeForm(request.GET or None)
    orders = list(_orders(request, form).prefetch_related("lines__product__category", "receipts__lines"))
    by_vendor = defaultdict(lambda: ZERO)
    by_cat = defaultdict(lambda: ZERO)
    by_project = defaultdict(lambda: ZERO)
    perf = defaultdict(lambda: {"pos": 0, "on_time": 0, "delivered": 0, "received": ZERO, "rejected": ZERO, "spend": ZERO})
    pr_to_po = []
    po_to_grn = []
    for po in orders:
        value = po.subtotal * po.exchange_rate
        by_vendor[po.vendor.name] += value
        by_project[po.project.code if po.project else "(no project)"] += value
        for l in po.lines.all():
            by_cat[l.product.category.name] += l.amount * po.exchange_rate
        p = perf[po.vendor.name]
        p["pos"] += 1
        p["spend"] += value
        posted = [g for g in po.receipts.all() if g.status == "posted"]
        if posted:
            first = min(g.date for g in posted)
            last = max(g.date for g in posted)
            p["delivered"] += 1
            if po.expected_date and last <= po.expected_date:
                p["on_time"] += 1
            po_to_grn.append((first - po.date).days)
            for g in posted:
                for gl in g.lines.all():
                    p["received"] += gl.received_qty
                    p["rejected"] += gl.rejected_qty
        if po.requisition_id:
            pr_to_po.append((po.date - po.requisition.date).days)

    def table(title, d):
        rows = [[k, round(v, 2)] for k, v in sorted(d.items(), key=lambda x: -x[1])]
        return Table(title, ["", "Spend (AED, excl. VAT)"], rows, total_row(rows, [1]))

    perf_rows = []
    for name, p in sorted(perf.items()):
        on_time = Decimal(p["on_time"] * 100 / p["delivered"]).quantize(Decimal("0.1")) if p["delivered"] else "—"
        rej = (p["rejected"] / p["received"] * 100).quantize(Decimal("0.1")) if p["received"] else "—"
        perf_rows.append([name, p["pos"], round(p["spend"], 2), p["delivered"], on_time, rej])
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else "—"  # noqa: E731
    kpis = [{"label": "Total spend", "value": f"{sum(by_vendor.values(), ZERO):,.0f}"},
            {"label": "Purchase orders", "value": len(orders)},
            {"label": "Avg PR → PO (days)", "value": avg(pr_to_po)},
            {"label": "Avg PO → first GRN (days)", "value": avg(po_to_grn)}]
    return render_report(request, "Purchase analytics", [
        table("Spend by vendor", by_vendor), table("Spend by category", by_cat), table("Spend by project", by_project),
        Table("Vendor performance", ["Vendor", "POs", "Spend", "Delivered POs", "On-time %", "Rejection %"], perf_rows),
    ], form, kpis=kpis)


def tracking(request):
    rows, links = [], []
    for po in PurchaseOrder.objects.exclude(status__in=["draft", "cancelled"]).select_related("vendor", "project"):
        for l in po.lines.select_related("product"):
            rows.append([po.number, po.vendor.name, po.project.code if po.project else "", po.get_status_display(),
                         po.expected_date, l.product.code, l.qty, l.received_qty, l.pending_qty, l.invoiced_qty])
            links.append(registry.url_for(po))
    return render_report(request, "PO tracking", [Table("Draft → Sent → Received → Closed",
                         ["PO", "Vendor", "Project", "Status", "Expected", "Item", "Ordered", "Received", "Pending",
                          "Invoiced"], rows, links=links)])
