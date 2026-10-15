from collections import defaultdict
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.db.models import F, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import ZERO
from core.reports import DateRangeForm, Table, render_report, total_row
from core.ui import registry

from .models import (GoodsReceipt, MaterialRequisition, Product, StockBalance, StockMove, StockTransfer, Warehouse)


class WarehouseForm(forms.Form):
    warehouse = forms.ModelChoiceField(Warehouse.objects.all(), required=False)


def valuation(request):
    form = WarehouseForm(request.GET or None)
    qs = StockBalance.objects.filter(qty__gt=0).select_related("product__category", "warehouse")
    if form.is_valid() and form.cleaned_data["warehouse"]:
        qs = qs.filter(warehouse=form.cleaned_data["warehouse"])
    rows = [[b.product.code, b.product.name, b.product.category.name, b.warehouse.code, b.qty, round(b.avg_cost, 4), b.value]
            for b in qs.order_by("product__code")]
    by_cat = defaultdict(lambda: ZERO)
    for r in rows:
        by_cat[r[2]] += r[6]
    t1 = Table("Stock valuation (weighted average cost)", ["Code", "Product", "Category", "Warehouse", "Qty", "Avg cost", "Value"],
               rows, total_row(rows, [6]))
    t2 = Table("By category", ["Category", "Value"], [[k, v] for k, v in sorted(by_cat.items())],
               total_row([[k, v] for k, v in by_cat.items()], [1]))
    return render_report(request, "Inventory valuation", [t1, t2], form)


def ageing(request):
    today = timezone.localdate()
    buckets = [(30, "0–30"), (60, "31–60"), (90, "61–90"), (180, "91–180"), (99999, "180+")]
    rows = []
    for b in StockBalance.objects.filter(qty__gt=0).select_related("product", "warehouse"):
        remaining = b.qty
        vals = [ZERO] * len(buckets)
        unit = b.avg_cost
        for m in StockMove.objects.filter(product=b.product, warehouse=b.warehouse, qty__gt=0).order_by("-date", "-id"):
            take = min(remaining, m.qty)
            age = (today - m.date).days
            idx = next(i for i, (lim, _) in enumerate(buckets) if age <= lim)
            vals[idx] += round(take * unit, 2)
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            vals[-1] += round(remaining * unit, 2)
        rows.append([b.product.code, b.product.name, b.warehouse.code, b.qty] + vals + [b.value])
    cols = list(range(4, 4 + len(buckets) + 1))
    return render_report(request, "Stock ageing", [Table("Value by age of receipt (days)",
                         ["Code", "Product", "WH", "Qty"] + [l for _, l in buckets] + ["Total"], rows, total_row(rows, cols))])


class MovementForm(DateRangeForm):
    product = forms.ModelChoiceField(Product.objects.filter(is_stock=True), required=False)
    warehouse = forms.ModelChoiceField(Warehouse.objects.all(), required=False)


def movement(request):
    form = MovementForm(request.GET or None)
    qs = StockMove.objects.select_related("product", "warehouse", "project", "bin")
    if form.is_valid():
        d = form.cleaned_data
        if d["date_from"]:
            qs = qs.filter(date__gte=d["date_from"])
        if d["date_to"]:
            qs = qs.filter(date__lte=d["date_to"])
        if d["product"]:
            qs = qs.filter(product=d["product"])
        if d["warehouse"]:
            qs = qs.filter(warehouse=d["warehouse"])
    rows = [[m.date, m.reference, m.move_type.replace("_", " "), m.product.code, m.warehouse.code,
             m.bin.code if m.bin else "", m.project.code if m.project else "", m.qty, m.unit_cost, m.value]
            for m in qs[:2000]]
    return render_report(request, "Stock movement", [Table("", ["Date", "Document", "Type", "Product", "WH", "Bin",
                                                                "Project", "Qty", "Unit cost", "Value"], rows)], form)


def consumption(request):
    form = DateRangeForm(request.GET or None)
    qs = StockMove.objects.filter(project__isnull=False, move_type__in=["issue", "project_return"])
    if form.is_valid():
        if form.cleaned_data["date_from"]:
            qs = qs.filter(date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data["date_to"]:
            qs = qs.filter(date__lte=form.cleaned_data["date_to"])
    data = qs.values("project__code", "project__name", "product__code", "product__name").annotate(
        q=Sum("qty"), v=Sum("value")).order_by("project__code", "product__code")
    rows = [[r["project__code"], r["project__name"], r["product__code"], r["product__name"], -r["q"], -r["v"]] for r in data]
    return render_report(request, "Material consumption by project",
                         [Table("Issues net of returns", ["Project", "Name", "Code", "Product", "Qty", "Value"], rows,
                                total_row(rows, [5]))], form)


def availability(request):
    rows = []
    links = []
    for p in Product.objects.filter(is_stock=True, active=True).select_related("uom"):
        on_hand = p.qty_on_hand()
        reserved = p.reserved_qty()
        on_order = p.on_order_qty()
        available = on_hand - reserved
        projected = available + on_order
        flag = "Below reorder" if projected < p.reorder_level else ""
        rows.append([p.code, p.name, p.uom.code, on_hand, reserved, available, on_order, projected, p.reorder_level, flag])
        links.append(registry.url_for(p))
    return render_report(request, "Availability, reservations & needs", [Table(
        "Real-time position (reserved = open material requisitions, on order = approved POs not received)",
        ["Code", "Product", "UoM", "On hand", "Reserved", "Available", "On order", "Projected", "Reorder level", ""],
        rows, links=links)])


def locations(request):
    data = StockMove.objects.values("warehouse__code", "bin__code", "product__code", "product__name").annotate(
        q=Sum("qty")).filter(~Q(q=0)).order_by("warehouse__code", "bin__code", "product__code")
    rows = [[r["warehouse__code"], r["bin__code"] or "(no bin)", r["product__code"], r["product__name"], r["q"]] for r in data]
    return render_report(request, "Stock by warehouse & bin", [Table("", ["Warehouse", "Bin", "Code", "Product", "Qty"], rows)])


def replenishment_candidates():
    out = []
    for p in Product.objects.filter(is_stock=True, active=True, reorder_level__gt=0):
        projected = p.qty_on_hand() - p.reserved_qty() + p.on_order_qty()
        if projected < p.reorder_level:
            qty = max(p.reorder_qty, p.reorder_level - projected)
            out.append((p, projected, qty))
    return out


def replenishment(request):
    from procurement.models import PurchaseRequisition, PurchaseRequisitionLine

    items = replenishment_candidates()
    if request.method == "POST":
        if not items:
            messages.info(request, "Nothing is below its reorder level.")
            return redirect("inv-replenishment")
        pr = PurchaseRequisition.objects.create(source="replenishment", warehouse=Warehouse.objects.order_by("id").first(),
                                                remarks="Raised automatically from reorder levels")
        for p, projected, qty in items:
            PurchaseRequisitionLine.objects.create(requisition=pr, product=p, qty=qty, estimated_rate=p.standard_cost)
        pr.recalc()
        messages.success(request, f"Purchase requisition {pr.number} raised for {len(items)} item(s).")
        return redirect(registry.url_for(pr))
    rows = [[p.code, p.name, p.reorder_level, projected, qty] for p, projected, qty in items]
    return render(request, "inventory/replenishment.html", {"rows": rows})


def dashboard(request):
    balances = StockBalance.objects.all()
    stock_value = balances.aggregate(v=Sum("value"))["v"] or ZERO
    low = replenishment_candidates()
    pending_grn = GoodsReceipt.objects.filter(status="draft").count()
    from procurement.models import PurchaseOrder

    awaiting = PurchaseOrder.objects.filter(status__in=["approved", "sent", "partially_received"]).count()
    pending_tr = StockTransfer.objects.filter(status="draft").count()
    open_mr = MaterialRequisition.objects.filter(status__in=["submitted", "partially_issued"]).count()
    by_wh = balances.values("warehouse__code", "warehouse__name").annotate(v=Sum("value"), n=Sum("qty"))
    recent = StockMove.objects.select_related("product", "warehouse")[:15]
    return render(request, "inventory/dashboard.html", {
        "kpis": [("Stock value", f"{stock_value:,.0f}"), ("Items below reorder", len(low)),
                 ("GRNs under inspection", pending_grn), ("POs awaiting delivery", awaiting),
                 ("Pending transfers", pending_tr), ("Open material requisitions", open_mr)],
        "low": low[:15], "by_wh": by_wh, "recent": recent,
    })
