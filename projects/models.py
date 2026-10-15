from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from core.models import ZERO, Doc, money_field, qty_field
from core.services import q2
from sales.models import COST_CATEGORIES


class Project(models.Model):
    STATUS = [("active", "Active"), ("on_hold", "On hold"), ("completed", "Completed"), ("closed", "Closed")]
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    customer = models.ForeignKey("sales.Customer", on_delete=models.PROTECT)
    quotation = models.ForeignKey("sales.Quotation", null=True, blank=True, on_delete=models.PROTECT)
    contract = models.ForeignKey("sales.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="projects")
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                verbose_name="Project manager")
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    contract_value = money_field(help_text="Original contract value excl. VAT")
    budget_material = money_field()
    budget_labour = money_field()
    budget_subcontract = money_field()
    budget_overhead = money_field()
    progress_percent = models.DecimalField("Progress %", max_digits=5, decimal_places=2, default=ZERO)
    status = models.CharField(max_length=20, choices=STATUS, default="active")
    closed_on = models.DateField(null=True, blank=True, editable=False)
    close_summary = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    # --- budget / actual -------------------------------------------------
    def vo_totals(self):
        agg = self.variations.filter(status="approved").aggregate(s=Sum("selling_total"), c=Sum("cost_total"))
        return agg["s"] or ZERO, agg["c"] or ZERO

    @property
    def revised_contract_value(self):
        return self.contract_value + self.vo_totals()[0]

    def budget_by_category(self):
        out = {"material": self.budget_material, "labour": self.budget_labour,
               "subcontract": self.budget_subcontract, "overhead": self.budget_overhead}
        for row in VariationLine.objects.filter(variation__project=self, variation__status="approved") \
                .values("category").annotate(t=Sum("cost_amount")):
            key = row["category"] if row["category"] in out else "overhead"
            out[key] += row["t"] or ZERO
        return out

    @property
    def total_budget(self):
        return sum(self.budget_by_category().values(), ZERO)

    def actual_by_category(self):
        from accounts.models import JournalLine

        out = {"material": ZERO, "labour": ZERO, "subcontract": ZERO, "overhead": ZERO}
        rows = (JournalLine.objects.filter(project=self, entry__status="posted", account__type="expense")
                .values("account__cost_category").annotate(d=Sum("base_debit"), c=Sum("base_credit")))
        for r in rows:
            key = r["account__cost_category"] or "overhead"
            if key not in out:
                key = "overhead"
            out[key] += (r["d"] or ZERO) - (r["c"] or ZERO)
        return out

    def revenue(self):
        from accounts.models import JournalLine

        agg = JournalLine.objects.filter(project=self, entry__status="posted", account__type="income") \
            .aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
        return (agg["c"] or ZERO) - (agg["d"] or ZERO)

    def invoiced(self):
        agg = self.customer_invoices.filter(status="posted").exclude(invoice_type__in=["advance", "retention"]) \
            .aggregate(t=Sum("gross_amount"))
        return agg["t"] or ZERO

    def profitability(self):
        actual = self.actual_by_category()
        revenue = self.revenue()
        direct = actual["material"] + actual["labour"] + actual["subcontract"]
        gp = revenue - direct
        np_ = gp - actual["overhead"]
        budget = self.budget_by_category()
        total_budget = sum(budget.values(), ZERO)
        total_actual = sum(actual.values(), ZERO)
        completion = (total_actual / total_budget) if total_budget else ZERO
        completion = min(completion, Decimal("1"))
        earned = q2(self.revised_contract_value * completion)
        return {
            "revenue": revenue, "direct_cost": direct, "overhead": actual["overhead"], "gp": gp, "np": np_,
            "gp_percent": q2(gp / revenue * 100) if revenue else ZERO,
            "np_percent": q2(np_ / revenue * 100) if revenue else ZERO,
            "budget": budget, "actual": actual, "total_budget": total_budget, "total_actual": total_actual,
            "cost_completion_percent": q2(completion * 100), "earned_revenue": earned,
            "invoiced": self.invoiced(), "unbilled": earned - self.invoiced(),
        }

    @property
    def detail_panel(self):
        from django.template.loader import render_to_string

        data = self.profitability()
        rows = []
        for key, label in (("material", "Material"), ("labour", "Labour"), ("subcontract", "Subcontract"),
                           ("overhead", "Overhead")):
            b, a = data["budget"][key], data["actual"][key]
            pct = int(a / b * 100) if b else (100 if a else 0)
            rows.append({"label": label, "budget": b, "actual": a, "variance": b - a, "pct": pct,
                         "bar": min(pct, 100)})
        return render_to_string("projects/panel.html", {"p": self, "data": data, "rows": rows})


class ProjectTask(models.Model):
    STATUS = [("todo", "Not started"), ("in_progress", "In progress"), ("done", "Done"), ("blocked", "Blocked")]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=200)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    percent_complete = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    status = models.CharField(max_length=20, choices=STATUS, default="todo")

    def __str__(self):
        return self.name


class ManpowerAllocation(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="manpower")
    employee = models.ForeignKey("hrms.Employee", on_delete=models.PROTECT)
    trade = models.ForeignKey("hrms.Trade", null=True, blank=True, on_delete=models.SET_NULL)
    date_from = models.DateField()
    date_to = models.DateField(null=True, blank=True)
    role = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.employee} → {self.project.code}"


class VariationOrder(Doc):
    SEQ_KEY, SEQ_PREFIX = "VO", "VO-"
    APPROVAL_DOC_TYPE = "variation_order"
    STATUS = [("draft", "Draft"), ("submitted", "Submitted for BOQ re-approval"), ("approved", "Approved"),
              ("rejected", "Rejected")]
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="variations")
    title = models.CharField(max_length=200)
    reason = models.TextField("Scope change", blank=True)
    client_reference = models.CharField(max_length=60, blank=True)
    cost_total = money_field(editable=False)
    selling_total = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def __str__(self):
        return f"{self.number} · {self.title}"

    def approval_amount(self):
        return self.selling_total

    def recalc(self):
        agg = self.lines.aggregate(c=Sum("cost_amount"), s=Sum("selling_amount"))
        self.cost_total = agg["c"] or ZERO
        self.selling_total = agg["s"] or ZERO
        self.save(update_fields=["cost_total", "selling_total"])


class VariationLine(models.Model):
    variation = models.ForeignKey(VariationOrder, on_delete=models.CASCADE, related_name="lines")
    category = models.CharField(max_length=20, choices=COST_CATEGORIES, default="material")
    description = models.CharField(max_length=250)
    qty = qty_field(default=Decimal("1"))
    uom = models.CharField("UoM", max_length=15, default="nos")
    unit_cost = money_field()
    selling_rate = money_field()
    cost_amount = money_field(editable=False)
    selling_amount = money_field(editable=False)

    def save(self, *args, **kwargs):
        self.cost_amount = q2(self.qty * self.unit_cost)
        self.selling_amount = q2(self.qty * self.selling_rate)
        super().save(*args, **kwargs)
