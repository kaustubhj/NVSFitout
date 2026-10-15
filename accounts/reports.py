import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.db.models import Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import ZERO
from projects.models import Project
from sales.models import Customer
from core.reports import DateRangeForm, Table, render_report, total_row
from core.ui import registry

from .models import (Account, BankAccount, BankStatementLine, Budget, CustomerInvoice, JournalLine, Receipt,
                     VendorInvoice)


def _range(form):
    today = timezone.localdate()
    d_from, d_to = date(today.year, 1, 1), today
    if form.is_valid():
        d_from = form.cleaned_data.get("date_from") or d_from
        d_to = form.cleaned_data.get("date_to") or d_to
    return d_from, d_to


def _posted(d_from=None, d_to=None):
    qs = JournalLine.objects.filter(entry__status="posted")
    if d_from:
        qs = qs.filter(entry__date__gte=d_from)
    if d_to:
        qs = qs.filter(entry__date__lte=d_to)
    return qs


def _balances(d_from=None, d_to=None, **filters):
    data = _posted(d_from, d_to).filter(**filters).values("account_id").annotate(d=Sum("base_debit"), c=Sum("base_credit"))
    return {r["account_id"]: (r["d"] or ZERO, r["c"] or ZERO) for r in data}


def trial_balance(request):
    form = DateRangeForm(request.GET or None)
    d_from, d_to = _range(form)
    opening = _balances(None, d_from - timedelta(days=1))
    period = _balances(d_from, d_to)
    rows, links = [], []
    for acc in Account.objects.filter(is_group=False).order_by("code"):
        od, oc = opening.get(acc.id, (ZERO, ZERO))
        pd, pc = period.get(acc.id, (ZERO, ZERO))
        if not any((od, oc, pd, pc)):
            continue
        ob = od - oc
        cb = ob + pd - pc
        rows.append([acc.code, acc.name, acc.get_type_display(), ob, pd, pc,
                     cb if cb > 0 else ZERO, -cb if cb < 0 else ZERO])
        links.append(f"/reports/accounts/ledger/?account={acc.id}&date_from={d_from}&date_to={d_to}")
    return render_report(request, "Trial balance", [Table(
        f"{d_from:%d %b %Y} – {d_to:%d %b %Y}", ["Code", "Account", "Type", "Opening (Dr−Cr)", "Debit", "Credit",
                                                 "Closing Dr", "Closing Cr"], rows, total_row(rows, [4, 5, 6, 7]),
        links=links)], form)


def _pl_data(d_from, d_to, project=None):
    filters = {"project": project} if project else {}
    bal = _balances(d_from, d_to, **filters)
    income, direct, indirect = [], [], []
    for acc in Account.objects.filter(is_group=False, type__in=["income", "expense"]).order_by("code"):
        d, c = bal.get(acc.id, (ZERO, ZERO))
        amount = c - d if acc.type == "income" else d - c
        if not amount:
            continue
        row = [acc.code, acc.name, amount]
        if acc.type == "income":
            income.append(row)
        elif acc.is_direct_cost:
            direct.append(row)
        else:
            indirect.append(row)
    ti = sum((r[2] for r in income), ZERO)
    td = sum((r[2] for r in direct), ZERO)
    tx = sum((r[2] for r in indirect), ZERO)
    return income, direct, indirect, ti, td, tx


def profit_loss(request):
    form = DateRangeForm(request.GET or None)
    d_from, d_to = _range(form)
    income, direct, indirect, ti, td, tx = _pl_data(d_from, d_to)
    gp, np_ = ti - td, ti - td - tx
    summary = [["Revenue", ti], ["Direct cost (material, labour, subcontract)", td], ["Gross profit", gp],
               ["Overheads", tx], ["Net profit", np_]]
    kpis = [{"label": "Revenue", "value": f"{ti:,.0f}"}, {"label": f"Gross profit ({(gp / ti * 100 if ti else 0):.1f}%)", "value": f"{gp:,.0f}"},
            {"label": f"Net profit ({(np_ / ti * 100 if ti else 0):.1f}%)", "value": f"{np_:,.0f}"}]
    return render_report(request, "Profit & loss", [
        Table("Revenue", ["Code", "Account", "Amount"], income, ["", "Total revenue", ti]),
        Table("Direct costs", ["Code", "Account", "Amount"], direct, ["", "Total direct cost", td]),
        Table("Overheads", ["Code", "Account", "Amount"], indirect, ["", "Total overheads", tx]),
        Table("Summary", ["", "Amount"], summary),
    ], form, kpis=kpis, note=f"{d_from:%d %b %Y} – {d_to:%d %b %Y}")


class AsOfForm(forms.Form):
    as_of = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))


def _as_of(form):
    if form.is_valid() and form.cleaned_data.get("as_of"):
        return form.cleaned_data["as_of"]
    return timezone.localdate()


def balance_sheet(request):
    form = AsOfForm(request.GET or None)
    as_of = _as_of(form)
    bal = _balances(None, as_of)
    sections = {"asset": [], "liability": [], "equity": []}
    for acc in Account.objects.filter(is_group=False, type__in=sections.keys()).order_by("code"):
        d, c = bal.get(acc.id, (ZERO, ZERO))
        amount = d - c if acc.type == "asset" else c - d
        if amount:
            sections[acc.type].append([acc.code, acc.name, amount])
    _, _, _, ti, td, tx = _pl_data(None, as_of)
    sections["equity"].append(["", "Current earnings (unclosed P&L)", ti - td - tx])
    ta = sum((r[2] for r in sections["asset"]), ZERO)
    tl = sum((r[2] for r in sections["liability"]), ZERO)
    te = sum((r[2] for r in sections["equity"]), ZERO)
    return render_report(request, "Balance sheet", [
        Table("Assets", ["Code", "Account", "Amount"], sections["asset"], ["", "Total assets", ta]),
        Table("Liabilities", ["Code", "Account", "Amount"], sections["liability"], ["", "Total liabilities", tl]),
        Table("Equity", ["Code", "Account", "Amount"], sections["equity"], ["", "Total equity", te]),
        Table("Check", ["", "Amount"], [["Assets − (liabilities + equity)", ta - tl - te]]),
    ], form, note=f"As of {as_of:%d %b %Y}")


class LedgerForm(DateRangeForm):
    account = forms.ModelChoiceField(Account.objects.filter(is_group=False))
    project = forms.ModelChoiceField(Project.objects.all(), required=False)


def ledger(request):
    form = LedgerForm(request.GET or None)
    tables = []
    if form.is_valid():
        acc = form.cleaned_data["account"]
        d_from, d_to = _range(form)
        filt = {"account": acc}
        if form.cleaned_data["project"]:
            filt["project"] = form.cleaned_data["project"]
        ob = _posted(None, d_from - timedelta(days=1)).filter(**filt).aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
        running = (ob["d"] or ZERO) - (ob["c"] or ZERO)
        rows = [[d_from, "", "Opening balance", "", "", "", running]]
        links = [None]
        for l in _posted(d_from, d_to).filter(**filt).select_related("entry", "project").order_by("entry__date", "entry_id"):
            running += l.base_debit - l.base_credit
            party = l.customer or l.vendor or l.employee or ""
            rows.append([l.entry.date, l.entry.number, l.description or l.entry.narration, str(party),
                         l.base_debit, l.base_credit, running])
            links.append(registry.url_for(l.entry))
        tables.append(Table(f"{acc} (balance shown as Dr − Cr)", ["Date", "Voucher", "Description", "Party", "Debit",
                                                                  "Credit", "Balance"], rows, links=links))
    return render_report(request, "General ledger", tables, form)


# --- receivables -------------------------------------------------------------------

class CustomerForm(DateRangeForm):
    customer = forms.ModelChoiceField(Customer.objects.all())


def soa(request):
    from .services import ctl

    form = CustomerForm(request.GET or None)
    tables, kpis = [], []
    if form.is_valid():
        cust = form.cleaned_data["customer"]
        d_from, d_to = _range(form)
        c = ctl()
        ar = c.receivable
        ob = _posted(None, d_from - timedelta(days=1)).filter(account=ar, customer=cust).aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
        running = (ob["d"] or ZERO) - (ob["c"] or ZERO)
        rows = [[d_from, "", "Opening balance", "", "", running]]
        for l in _posted(d_from, d_to).filter(account=ar, customer=cust).select_related("entry", "project").order_by("entry__date", "entry_id"):
            running += l.base_debit - l.base_credit
            rows.append([l.entry.date, l.entry.number, l.entry.narration, l.base_debit, l.base_credit, running])
        tables.append(Table(f"Statement of account — {cust.name}", ["Date", "Voucher", "Description", "Debit", "Credit",
                                                                     "Balance"], rows))
        adv = _posted(None, d_to).filter(account=c.customer_advance, customer=cust).aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
        ret = _posted(None, d_to).filter(account=c.retention_receivable, customer=cust).aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
        pdcs = Receipt.objects.filter(customer=cust, status="pdc")
        tables.append(Table("Post-dated cheques in hand", ["Receipt", "Cheque", "Cheque date", "Amount"],
                            [[r.number, r.cheque_no, r.cheque_date, r.amount] for r in pdcs]))
        kpis = [{"label": "Balance due", "value": f"{running:,.2f}"},
                {"label": "Advance held", "value": f"{(adv['c'] or 0) - (adv['d'] or 0):,.2f}"},
                {"label": "Retention receivable", "value": f"{(ret['d'] or 0) - (ret['c'] or 0):,.2f}"},
                {"label": "PDCs in hand", "value": f"{sum((p.amount for p in pdcs), ZERO):,.2f}"}]
    return render_report(request, "Customer SOA (with advance & PDC)", tables, form, kpis=kpis)


AGE_BUCKETS = [(0, "Not due"), (30, "1–30"), (60, "31–60"), (90, "61–90"), (180, "91–180"), (10 ** 6, "180+")]


def _bucket(days_overdue):
    if days_overdue <= 0:
        return 0
    for i, (lim, _) in enumerate(AGE_BUCKETS[1:], start=1):
        if days_overdue <= lim:
            return i
    return len(AGE_BUCKETS) - 1


def _ageing(docs, key, as_of):
    data = defaultdict(lambda: [ZERO] * len(AGE_BUCKETS))
    for d in docs:
        if d.balance <= 0:
            continue
        due = d.due_date or d.date
        data[key(d)][_bucket((as_of - due).days)] += d.balance
    rows = [[k] + v + [sum(v, ZERO)] for k, v in sorted(data.items())]
    return rows


def ar_ageing(request):
    form = AsOfForm(request.GET or None)
    as_of = _as_of(form)
    invs = list(CustomerInvoice.objects.filter(status="posted", date__lte=as_of).select_related("customer", "project"))
    headers = [l for _, l in AGE_BUCKETS] + ["Total"]
    cols = list(range(1, len(AGE_BUCKETS) + 2))
    by_c = _ageing(invs, lambda i: i.customer.name, as_of)
    by_p = _ageing(invs, lambda i: i.project.code if i.project else "(no project)", as_of)
    detail = [[i.number, i.customer.name, i.project.code if i.project else "", i.date, i.due_date, i.total, i.balance,
               max((as_of - (i.due_date or i.date)).days, 0)] for i in invs if i.balance > 0]
    return render_report(request, "Receivables ageing", [
        Table("By customer", ["Customer"] + headers, by_c, total_row(by_c, cols)),
        Table("Project-wise", ["Project"] + headers, by_p, total_row(by_p, cols)),
        Table("Open invoices", ["Invoice", "Customer", "Project", "Date", "Due", "Total", "Balance", "Days overdue"], detail),
    ], form, note=f"As of {as_of:%d %b %Y}")


def ap_ageing(request):
    form = AsOfForm(request.GET or None)
    as_of = _as_of(form)
    invs = list(VendorInvoice.objects.filter(status="posted", date__lte=as_of).select_related("vendor"))
    rows = _ageing(invs, lambda i: i.vendor.name, as_of)
    cols = list(range(1, len(AGE_BUCKETS) + 2))
    return render_report(request, "Payables ageing", [Table("By vendor", ["Vendor"] + [l for _, l in AGE_BUCKETS] + ["Total"],
                                                             rows, total_row(rows, cols))], form)


def unbilled(request):
    rows, links = [], []
    for p in Project.objects.exclude(status="closed").order_by("code"):
        d = p.profitability()
        rows.append([p.code, p.name, p.revised_contract_value, d["total_budget"], d["total_actual"],
                     d["cost_completion_percent"], d["earned_revenue"], d["invoiced"], d["unbilled"]])
        links.append(registry.url_for(p))
    return render_report(request, "Unbilled revenue (IFRS 15)", [Table(
        "Input method: cost-to-cost. Earned = revised contract × actual cost ÷ budget cost; unbilled = earned − invoiced "
        "(positive = contract asset, negative = billing in excess)",
        ["Code", "Project", "Revised contract", "Budget cost", "Actual cost", "Completion %", "Earned", "Invoiced",
         "Unbilled"], rows, total_row(rows, [2, 3, 4, 6, 7, 8]), links=links)])


def retention(request):
    from core.models import Company

    days = Company.get().retention_due_days
    today = timezone.localdate()
    rows, links = [], []
    from sales.models import Contract

    for c in Contract.objects.select_related("customer"):
        held = c.invoices.filter(status="posted").aggregate(t=Sum("retention_amount"))["t"] or ZERO
        released = c.invoices.filter(status="posted", invoice_type="retention").aggregate(t=Sum("gross_amount"))["t"] or ZERO
        if not held:
            continue
        final = c.invoices.filter(status="posted", invoice_type="final").order_by("-date").first()
        due = final.date + timedelta(days=days) if final else None
        status = "Awaiting final invoice" if not due else ("Due now" if due <= today else f"Due in {(due - today).days} days")
        rows.append([c.number, c.customer.name, c.client_po_number, held, released, held - released,
                     final.date if final else None, due, status])
        links.append(registry.url_for(c))
    return render_report(request, "Retention per project", [Table(
        f"Retention is due {days} days after the final invoice", ["Contract", "Customer", "Client PO", "Retention held",
                                                                   "Released", "Outstanding", "Final invoice", "Due date",
                                                                   "Status"], rows, total_row(rows, [3, 4, 5]), links=links)])


class BudgetForm(forms.Form):
    year = forms.IntegerField(required=False)
    month = forms.IntegerField(required=False, min_value=1, max_value=12, help_text="YTD up to month")


def budget_vs_actual(request):
    form = BudgetForm(request.GET or None)
    today = timezone.localdate()
    year, month = today.year, today.month
    if form.is_valid():
        year = form.cleaned_data["year"] or year
        month = form.cleaned_data["month"] or month
    end = date(year, month, 28) + timedelta(days=4)
    end = end - timedelta(days=end.day)
    rows = []
    for b in Budget.objects.filter(fiscal_year=year).select_related("account", "project"):
        actual = b.account.balance(date_from=date(year, 1, 1), date_to=end, project=b.project)
        budget_ytd = b.upto(month)
        forecast = round(actual / month * 12, 2) if month else ZERO
        rows.append([b.account.code, b.account.name, b.project.code if b.project else "", b.annual, budget_ytd, actual,
                     budget_ytd - actual, forecast, b.annual - forecast])
    return render_report(request, "Budget vs actual & forecast", [Table(
        f"YTD to {end:%b %Y}; forecast = run-rate (YTD ÷ months × 12)",
        ["Code", "Account", "Project", "Annual budget", "Budget YTD", "Actual YTD", "Variance YTD", "Forecast FY",
         "Forecast variance"], rows, total_row(rows, [3, 4, 5, 6, 7, 8]))], form)


def monthly(request):
    form = BudgetForm(request.GET or None)
    year = timezone.localdate().year
    if form.is_valid() and form.cleaned_data["year"]:
        year = form.cleaned_data["year"]
    rec_rows, pl_rows = [], []
    for m in range(1, 13):
        start = date(year, m, 1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        invoiced = CustomerInvoice.objects.filter(status="posted", date__range=(start, end)).aggregate(t=Sum("total"))["t"] or ZERO
        collected = Receipt.objects.filter(status__in=["posted", "cleared", "pdc"], date__range=(start, end)).aggregate(t=Sum("amount"))["t"] or ZERO
        outstanding = sum((i.balance for i in CustomerInvoice.objects.filter(status="posted", date__lte=end)), ZERO)
        rec_rows.append([start.strftime("%b %Y"), invoiced, collected, outstanding])
        _, _, _, ti, td, tx = _pl_data(start, end)
        pl_rows.append([start.strftime("%b %Y"), ti, td, ti - td, tx, ti - td - tx])
    return render_report(request, f"Monthly receivable & profitability {year}", [
        Table("Monthly receivable", ["Month", "Invoiced", "Collected", "Outstanding at month end"], rec_rows,
              total_row(rec_rows, [1, 2])),
        Table("Monthly profitability", ["Month", "Revenue", "Direct cost", "Gross profit", "Overheads", "Net profit"],
              pl_rows, total_row(pl_rows, [1, 2, 3, 4, 5])),
    ], form)


def vat(request):
    from .services import ctl

    form = DateRangeForm(request.GET or None)
    d_from, d_to = _range(form)
    c = ctl()
    out = _posted(d_from, d_to).filter(account=c.vat_output).aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
    inp = _posted(d_from, d_to).filter(account=c.vat_input).aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
    output = (out["c"] or 0) - (out["d"] or 0)
    input_ = (inp["d"] or 0) - (inp["c"] or 0)
    return render_report(request, "VAT summary", [Table("", ["", "Amount"], [["Output VAT", output], ["Input VAT", input_],
                                                                            ["Net payable", output - input_]])], form)


def analytics(request):
    from .services import ctl

    today = timezone.localdate()
    c = ctl()
    bal = _balances(None, today)
    by_type = defaultdict(lambda: ZERO)
    current_assets = ZERO
    for acc in Account.objects.filter(is_group=False):
        d, cr = bal.get(acc.id, (ZERO, ZERO))
        amt = d - cr if acc.debit_normal else cr - d
        by_type[acc.type] += amt
    ar = c.receivable.balance() if c.receivable else ZERO
    ap = c.payable.balance() if c.payable else ZERO
    start = date(today.year, 1, 1)
    _, _, _, ti, td, tx = _pl_data(start, today)
    days = max((today - start).days, 1)
    dso = round(ar / ti * days, 0) if ti else "—"
    dpo = round(ap / td * days, 0) if td else "—"
    cash = sum((b.account.balance() for b in BankAccount.objects.select_related("account")), ZERO)
    kpis = [{"label": "Cash & bank", "value": f"{cash:,.0f}"}, {"label": "Receivables", "value": f"{ar:,.0f}"},
            {"label": "Payables", "value": f"{ap:,.0f}"}, {"label": "DSO (days)", "value": dso},
            {"label": "DPO (days)", "value": dpo},
            {"label": "GP margin YTD", "value": f"{((ti - td) / ti * 100 if ti else 0):.1f}%"},
            {"label": "NP margin YTD", "value": f"{((ti - td - tx) / ti * 100 if ti else 0):.1f}%"}]
    rows = [[t.title(), v] for t, v in by_type.items()]
    return render_report(request, "Financial analytics", [Table("Balances by type", ["Type", "Balance"], rows)], kpis=kpis)


# --- bank reconciliation -----------------------------------------------------------

class StatementUploadForm(forms.Form):
    bank_account = forms.ModelChoiceField(BankAccount.objects.all())
    file = forms.FileField(help_text="CSV columns: date (YYYY-MM-DD), description, reference, amount (+ in / − out)")


def bank_reconciliation(request):
    banks = BankAccount.objects.all()
    bank = banks.filter(pk=request.GET.get("bank") or request.POST.get("bank")).first() or banks.first()
    if request.method == "POST" and bank:
        action = request.POST.get("action")
        if action == "upload":
            f = request.FILES.get("file")
            n = 0
            try:
                for row in csv.DictReader(io.StringIO(f.read().decode("utf-8-sig"))):
                    BankStatementLine.objects.create(
                        bank_account=bank, date=date.fromisoformat(row["date"].strip()),
                        description=row.get("description", "")[:250], reference=row.get("reference", "")[:80],
                        amount=Decimal(row["amount"].replace(",", "")))
                    n += 1
                messages.success(request, f"{n} statement line(s) imported.")
            except (KeyError, ValueError, InvalidOperation) as e:
                messages.error(request, f"Could not read the file: {e}")
        elif action == "auto":
            n = auto_match(bank)
            messages.success(request, f"{n} line(s) matched automatically.")
        elif action == "match":
            sl = BankStatementLine.objects.get(pk=request.POST["statement_line"], bank_account=bank)
            jl = JournalLine.objects.get(pk=request.POST["journal_line"], account=bank.account)
            sl.matched_line = jl
            sl.save()
            jl.reconciled = True
            jl.save(update_fields=["reconciled"])
            messages.success(request, "Matched.")
        elif action == "unmatch":
            sl = BankStatementLine.objects.get(pk=request.POST["statement_line"], bank_account=bank)
            if sl.matched_line:
                sl.matched_line.reconciled = False
                sl.matched_line.save(update_fields=["reconciled"])
            sl.matched_line = None
            sl.save()
        return redirect(f"{request.path}?bank={bank.pk}")
    ctx = {"banks": banks, "bank": bank, "form": StatementUploadForm()}
    if bank:
        unmatched_stmt = bank.statement_lines.filter(matched_line__isnull=True)
        unmatched_gl = JournalLine.objects.filter(account=bank.account, entry__status="posted",
                                                  reconciled=False).select_related("entry").order_by("entry__date")
        book = bank.account.balance()
        stmt = bank.statement_lines.aggregate(t=Sum("amount"))["t"] or ZERO
        ctx.update({
            "unmatched_stmt": unmatched_stmt, "unmatched_gl": unmatched_gl,
            "matched": bank.statement_lines.filter(matched_line__isnull=False).select_related("matched_line__entry")[:50],
            "book": book, "statement": stmt,
            "uncleared_in": sum((l.base_debit for l in unmatched_gl), ZERO),
            "uncleared_out": sum((l.base_credit for l in unmatched_gl), ZERO),
        })
        ctx["difference"] = book - ctx["uncleared_in"] + ctx["uncleared_out"] - stmt
    return render(request, "accounts/bank_rec.html", ctx)


def auto_match(bank):
    n = 0
    for sl in bank.statement_lines.filter(matched_line__isnull=True):
        amount = abs(sl.amount)
        q = JournalLine.objects.filter(account=bank.account, reconciled=False,
                                       entry__date__range=(sl.date - timedelta(days=7), sl.date + timedelta(days=7)))
        q = q.filter(base_debit=amount) if sl.amount > 0 else q.filter(base_credit=amount)
        jl = q.order_by("entry__date").first()
        if jl:
            sl.matched_line = jl
            sl.save()
            jl.reconciled = True
            jl.save(update_fields=["reconciled"])
            n += 1
    return n
