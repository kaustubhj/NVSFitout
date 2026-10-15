from collections import defaultdict
from datetime import timedelta

from django import forms
from django.db.models import Sum
from django.utils import timezone

from core.models import ZERO
from core.reports import DateRangeForm, Table, render_report, total_row

from .models import Attendance, Camp, Employee, EmployeeDocument, PayrollRun, PayslipCost, VisaQuota
from .services import gratuity, ticket_accrual


def eos(request):
    today = timezone.localdate()
    rows = []
    for e in Employee.objects.filter(status__in=["active", "on_leave"]).select_related("designation"):
        amount, years = gratuity(e, today)
        rows.append([e.code, e.name, e.get_employee_type_display(), e.joining_date, round(years, 2), e.basic_salary,
                     amount, e.get_ticket_category_display(), ticket_accrual(e, today)])
    return render_report(request, "EOS & air ticket provision", [Table(
        f"As of {today:%d %b %Y} — gratuity: 21 days' basic per year (first 5 years), 30 days after, capped at 24 months",
        ["Code", "Employee", "Type", "Joined", "Years", "Basic", "Gratuity", "Ticket category", "Ticket accrued"],
        rows, total_row(rows, [6, 8]))])


def labour_cost(request):
    form = DateRangeForm(request.GET or None)
    qs = PayslipCost.objects.select_related("payslip__run", "project")
    if form.is_valid():
        if form.cleaned_data["date_from"]:
            qs = qs.filter(payslip__run__date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data["date_to"]:
            qs = qs.filter(payslip__run__date__lte=form.cleaned_data["date_to"])
    data = qs.values("payslip__run__year", "payslip__run__month", "project__code").annotate(h=Sum("hours"), a=Sum("amount")) \
        .order_by("payslip__run__year", "payslip__run__month", "project__code")
    rows = [[f"{r['payslip__run__month']:02d}/{r['payslip__run__year']}", r["project__code"] or "(overhead)", r["h"], r["a"]]
            for r in data]
    return render_report(request, "Payroll cost allocation by project",
                         [Table("", ["Month", "Project", "Hours", "Cost"], rows, total_row(rows, [2, 3]))], form)


def overtime(request):
    form = DateRangeForm(request.GET or None)
    qs = Attendance.objects.filter(status="P").select_related("employee", "sheet__project")
    if form.is_valid():
        if form.cleaned_data["date_from"]:
            qs = qs.filter(sheet__date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data["date_to"]:
            qs = qs.filter(sheet__date__lte=form.cleaned_data["date_to"])
    data = qs.values("employee__code", "employee__name", "sheet__project__code").annotate(
        h=Sum("hours_worked"), n=Sum("normal_ot"), f=Sum("friday_ot"), ho=Sum("holiday_ot")).order_by("employee__code")
    rows = [[r["employee__code"], r["employee__name"], r["sheet__project__code"], r["h"], r["n"], r["f"], r["ho"]] for r in data]
    return render_report(request, "Overtime summary", [Table(
        "Hours by employee and project", ["Code", "Employee", "Project", "Hours worked", "Normal OT", "Friday OT",
                                           "Holiday OT"], rows, total_row(rows, [3, 4, 5, 6]))], form)


def trade_hours(request):
    form = DateRangeForm(request.GET or None)
    qs = Attendance.objects.filter(status="P")
    if form.is_valid():
        if form.cleaned_data["date_from"]:
            qs = qs.filter(sheet__date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data["date_to"]:
            qs = qs.filter(sheet__date__lte=form.cleaned_data["date_to"])
    data = qs.values("trade__name", "sheet__project__code").annotate(
        h=Sum("hours_worked"), ot=Sum("normal_ot") + Sum("friday_ot") + Sum("holiday_ot")).order_by("trade__name")
    rows = [[r["trade__name"] or "(no trade)", r["sheet__project__code"], r["h"], r["ot"]] for r in data]
    return render_report(request, "Trade hours", [Table("Hours by trade and project", ["Trade", "Project", "Hours", "OT hours"],
                                                         rows, total_row(rows, [2, 3]))], form)


def documents(request):
    today = timezone.localdate()
    soon = today + timedelta(days=60)
    qs = EmployeeDocument.objects.filter(expiry_date__isnull=False, expiry_date__lte=soon,
                                         employee__status__in=["active", "on_leave"]).select_related("employee") \
        .order_by("expiry_date")
    rows = [[d.employee.code, d.employee.name, d.get_doc_type_display(), d.number, d.expiry_date,
             "Expired" if d.expiry_date < today else f"{(d.expiry_date - today).days} days"] for d in qs]
    return render_report(request, "Document expiry (next 60 days)", [Table("", ["Code", "Employee", "Document", "Number",
                                                                               "Expiry", "Status"], rows)])


def camps(request):
    rows = []
    for c in Camp.objects.prefetch_related("rooms"):
        for r in c.rooms.all():
            rows.append([c.name, r.number, r.capacity, r.occupied, r.capacity - r.occupied])
    visa = [[v.establishment, str(v.designation or "Any"), v.quota, v.used, v.quota - v.used] for v in VisaQuota.objects.all()]
    return render_report(request, "Camps & visas", [
        Table("Room occupancy", ["Camp", "Room", "Capacity", "Occupied", "Free"], rows, total_row(rows, [2, 3, 4])),
        Table("Visa allocation", ["Establishment", "Designation", "Quota", "Used", "Available"], visa, total_row(visa, [2, 3, 4])),
    ])


def payroll_summary(request):
    rows = [[f"{r.month:02d}/{r.year}", r.number, r.get_employee_type_display(), r.payslips.count(), r.total_gross,
             r.total_deductions, r.total_net, r.total_cash_ot, r.get_status_display()]
            for r in PayrollRun.objects.order_by("-year", "-month")]
    return render_report(request, "Payroll summary", [Table("", ["Month", "Run", "Type", "Employees", "Gross", "Deductions",
                                                                  "Net (WPS)", "Cash OT", "Status"], rows)])
