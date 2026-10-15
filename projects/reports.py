from django import forms

from core.models import ZERO
from core.reports import Table, render_report, total_row
from core.ui import registry

from .models import Project


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=[("", "All")] + Project.STATUS, required=False)


def _projects(request):
    form = StatusForm(request.GET or None)
    qs = Project.objects.select_related("customer").order_by("code")
    if form.is_valid() and form.cleaned_data["status"]:
        qs = qs.filter(status=form.cleaned_data["status"])
    return form, qs


def portfolio(request):
    form, qs = _projects(request)
    rows, links = [], []
    for p in qs:
        d = p.profitability()
        rows.append([p.code, p.name, p.get_status_display(), p.revised_contract_value, d["total_budget"],
                     d["total_actual"], d["revenue"], d["gp"], d["gp_percent"], d["np"], d["np_percent"],
                     d["cost_completion_percent"], d["unbilled"]])
        links.append(registry.url_for(p))
    return render_report(request, "Project GP & NP", [Table(
        "Profit report", ["Code", "Project", "Status", "Revised contract", "Budget", "Actual cost", "Revenue", "GP", "GP %",
                          "NP", "NP %", "Cost completion %", "Unbilled"],
        rows, total_row(rows, [3, 4, 5, 6, 7, 9, 12]), links=links)], form)


def variance(request):
    form, qs = _projects(request)
    rows, links = [], []
    for p in qs:
        b, a = p.budget_by_category(), p.actual_by_category()
        row = [p.code, p.name]
        for k in ("material", "labour", "subcontract", "overhead"):
            row += [b[k], a[k], b[k] - a[k]]
        rows.append(row)
        links.append(registry.url_for(p))
    headers = ["Code", "Project"]
    for k in ("Material", "Labour", "Subcontract", "Overhead"):
        headers += [f"{k} budget", f"{k} actual", f"{k} variance"]
    return render_report(request, "Material / labour / subcontract variance", [
        Table("Budget vs actual by cost category (budget includes approved variation orders)", headers, rows,
              total_row(rows, list(range(2, 14))), links=links)], form)


class ProjectForm(forms.Form):
    project = forms.ModelChoiceField(Project.objects.all())


def costing(request):
    from accounts.models import JournalLine

    form = ProjectForm(request.GET or None)
    tables = []
    if form.is_valid():
        p = form.cleaned_data["project"]
        lines = JournalLine.objects.filter(project=p, entry__status="posted").select_related("entry", "account") \
            .order_by("entry__date", "entry__id")
        rows = [[l.entry.date, l.entry.number, l.account.code, l.account.name, l.account.get_cost_category_display(),
                 l.description, l.base_debit - l.base_credit if l.account.type == "expense" else ZERO,
                 l.base_credit - l.base_debit if l.account.type == "income" else ZERO]
                for l in lines if l.account.type in ("expense", "income")]
        tables.append(Table(f"{p} — cost & revenue postings",
                            ["Date", "Voucher", "Account", "Name", "Category", "Description", "Cost", "Revenue"],
                            rows, total_row(rows, [6, 7])))
    return render_report(request, "Project costing detail", tables, form)
