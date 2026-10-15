"""Payroll, overtime, EOS and air-ticket calculations."""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from core.models import ZERO, Company
from core.services import q2

from .models import Attendance, Deduction, Employee, LeaveApplication, Loan, Payslip, PayslipCost

THIRTY = Decimal("30")


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _overlap_days(a_from, a_to, b_from, b_to):
    start, end = max(a_from, b_from), min(a_to, b_to)
    return max((end - start).days + 1, 0)


def gratuity(employee, as_of=None):
    """UAE end-of-service gratuity on basic salary: 21 days per year for the first five years,
    30 days per year after, capped at two years' wages. Under one year of service: nil."""
    as_of = as_of or date.today()
    days = (as_of - employee.joining_date).days
    years = Decimal(days) / Decimal("365")
    if years < 1:
        return ZERO, years
    daily = employee.basic_salary / THIRTY
    first = min(years, Decimal("5")) * 21 * daily
    rest = max(years - 5, ZERO) * 30 * daily
    cap = employee.basic_salary * 24
    return q2(min(first + rest, cap)), years


def ticket_accrual(employee, as_of=None):
    """Air ticket accrued since the last entitlement date."""
    as_of = as_of or date.today()
    period = {"A": 12, "B": 12, "C": 24}.get(employee.ticket_category)
    if not period or not employee.ticket_amount:
        return ZERO
    months = (as_of.year - employee.joining_date.year) * 12 + as_of.month - employee.joining_date.month
    months_in_period = months % period
    return q2(employee.ticket_amount * months_in_period / period)


def process_payroll(run):
    company = Company.get()
    start, end = month_bounds(run.year, run.month)
    run.payslips.all().delete()
    LeaveApplication.objects.filter(paid_in_payroll=run).update(paid_in_payroll=None)
    Deduction.objects.filter(payroll=run).update(payroll=None)
    employees = Employee.objects.filter(status__in=["active", "on_leave"], joining_date__lte=end)
    if run.employee_type != "all":
        employees = employees.filter(employee_type=run.employee_type)
    totals = defaultdict(lambda: ZERO)
    for emp in employees:
        att = Attendance.objects.filter(employee=emp, sheet__date__range=(start, end)).select_related("sheet")
        absent = att.filter(status="A").count()
        # unpaid leave
        unpaid_days = 0
        advance_paid_days = 0
        for lv in LeaveApplication.objects.filter(employee=emp, status__in=["approved", "taken"],
                                                  date_from__lte=end, date_to__gte=start).select_related("leave_type"):
            d = _overlap_days(lv.date_from, lv.date_to, start, end)
            if not lv.leave_type.paid:
                unpaid_days += d
            elif lv.leave_salary_in_advance and lv.paid_in_payroll_id and lv.paid_in_payroll_id != run.id:
                advance_paid_days += d
        # joining mid-month
        not_joined = max((emp.joining_date - start).days, 0) if emp.joining_date > start else 0
        lost_days = Decimal(min(absent + unpaid_days + not_joined, 30))
        days_payable = THIRTY - lost_days
        confirmed = att.filter(sheet__status="confirmed")
        ot = confirmed.aggregate(n=Sum("normal_ot"), f=Sum("friday_ot"), h=Sum("holiday_ot"))
        n_ot, f_ot, h_ot = ot["n"] or ZERO, ot["f"] or ZERO, ot["h"] or ZERO
        if emp.employee_type == "hired" and emp.hourly_rate:
            normal_hours = att.aggregate(h=Sum("normal_hours"))["h"] or ZERO
            basic = q2(normal_hours * emp.hourly_rate)
            allowances = ZERO
            hourly = emp.hourly_rate
            days_payable = Decimal(att.filter(status="P").count())
        else:
            basic = q2(emp.basic_salary * days_payable / THIRTY)
            allowances = q2((emp.housing_allowance + emp.transport_allowance + emp.other_allowance) * days_payable / THIRTY)
            hourly = emp.basic_salary * 12 / 365 / emp.standard_hours()
        ot_amount = q2(hourly * (n_ot * company.normal_ot_rate + f_ot * company.friday_ot_rate +
                                 h_ot * company.holiday_ot_rate))
        cash_ot = ZERO
        if emp.cash_ot:
            cash_ot, ot_amount = ot_amount, ZERO
        # leave salary in advance (paid before the leave starts)
        leave_salary = ZERO
        ny, nm = (run.year, run.month + 1) if run.month < 12 else (run.year + 1, 1)
        next_end = month_bounds(ny, nm)[1]
        for lv in LeaveApplication.objects.filter(employee=emp, status="approved", leave_salary_in_advance=True,
                                                  paid_in_payroll__isnull=True, date_from__lte=next_end):
            lv.recalc()
            leave_salary += lv.leave_salary_amount
            lv.paid_in_payroll = run
            lv.save(update_fields=["paid_in_payroll"])
        unpaid_leave_deduction = q2((emp.basic_salary + emp.housing_allowance) / THIRTY * advance_paid_days)
        food = emp.food_deduction
        other = ZERO
        for d in Deduction.objects.filter(employee=emp, year=run.year, month=run.month, payroll__isnull=True):
            if d.deduction_type == "food":
                food += d.amount
            else:
                other += d.amount
            d.payroll = run
            d.save(update_fields=["payroll"])
        loan_recovery = ZERO
        for loan in Loan.objects.filter(employee=emp, status="active"):
            loan_recovery += min(loan.monthly_installment, loan.balance)
        gross = basic + allowances + ot_amount + leave_salary - unpaid_leave_deduction
        net = gross - food - loan_recovery - other
        if net < 0:
            raise ValidationError(f"{emp}: deductions exceed earnings this month; review loans / deductions.")
        slip = Payslip.objects.create(
            run=run, employee=emp, days_payable=days_payable, basic=basic, allowances=allowances,
            normal_ot_hours=n_ot, friday_ot_hours=f_ot, holiday_ot_hours=h_ot, ot_amount=ot_amount,
            cash_ot_amount=cash_ot, leave_salary=leave_salary, food_deduction=food, loan_recovery=loan_recovery,
            other_deductions=other, unpaid_leave_deduction=unpaid_leave_deduction, gross=gross, net=net,
        )
        # cost allocation by project from attendance hours
        cost = gross + cash_ot
        hours = defaultdict(lambda: ZERO)
        for a in att.filter(status="P"):
            hours[a.sheet.project_id] += a.normal_hours + a.normal_ot + a.friday_ot + a.holiday_ot
        total_hours = sum(hours.values(), ZERO)
        if total_hours:
            remaining = cost
            items = list(hours.items())
            for i, (pid, h) in enumerate(items):
                amt = remaining if i == len(items) - 1 else q2(cost * h / total_hours)
                remaining -= amt
                PayslipCost.objects.create(payslip=slip, project_id=pid, hours=h, amount=amt)
        else:
            PayslipCost.objects.create(payslip=slip, project=None, hours=ZERO, amount=cost)
        totals["gross"] += gross
        totals["ded"] += food + loan_recovery + other
        totals["net"] += net
        totals["cash"] += cash_ot
    run.total_gross, run.total_deductions = totals["gross"], totals["ded"]
    run.total_net, run.total_cash_ot = totals["net"], totals["cash"]
    run.status = "processed"
    run.save()
    return run.payslips.count()


def post_payroll(run):
    from accounts.services import ctl, post_journal

    c = ctl()
    _, end = month_bounds(run.year, run.month)
    journal = []
    by_project = defaultdict(lambda: ZERO)
    for cost in PayslipCost.objects.filter(payslip__run=run):
        by_project[cost.project_id] += cost.amount
    from projects.models import Project

    for pid, amt in by_project.items():
        if pid:
            journal.append({"account": c.require("labour_cost"), "debit": amt, "project": Project.objects.get(pk=pid),
                            "description": "Payroll cost allocation"})
        else:
            journal.append({"account": c.require("staff_cost"), "debit": amt, "description": "Payroll (no project)"})
    agg = run.payslips.aggregate(net=Sum("net"), cash=Sum("cash_ot_amount"), loan=Sum("loan_recovery"),
                                 food=Sum("food_deduction"), other=Sum("other_deductions"))
    journal.append({"account": c.require("payroll_payable"), "credit": (agg["net"] or 0) + (agg["cash"] or 0),
                    "description": "Net salaries + cash OT"})
    if agg["loan"]:
        journal.append({"account": c.require("employee_loans"), "credit": agg["loan"], "description": "Loan recovery"})
    recoveries = (agg["food"] or 0) + (agg["other"] or 0)
    if recoveries:
        journal.append({"account": c.require("payroll_recoveries"), "credit": recoveries, "description": "Food, fines & other"})
    entry = post_journal(end, journal, "PAY", f"Payroll {run.month:02d}/{run.year}", source=run)
    for slip in run.payslips.filter(loan_recovery__gt=0):
        remaining = slip.loan_recovery
        for loan in Loan.objects.filter(employee=slip.employee, status="active").order_by("id"):
            take = min(remaining, loan.balance, loan.monthly_installment)
            loan.recovered += take
            remaining -= take
            if loan.balance <= 0:
                loan.status = "closed"
            loan.save()
    run.status = "posted"
    run.save(update_fields=["status"])
    return entry


def wps_rows(run):
    """WPS Salary Information File (SIF) rows: EDR per employee + SCR control record."""
    company = Company.get()
    start, end = month_bounds(run.year, run.month)
    rows = []
    total = ZERO
    count = 0
    for s in run.payslips.select_related("employee").filter(net__gt=0):
        e = s.employee
        fixed = s.basic + s.allowances - s.unpaid_leave_deduction - s.food_deduction - s.loan_recovery - s.other_deductions
        variable = s.ot_amount + s.leave_salary
        rows.append(["EDR", e.wps_person_id or e.code, e.bank_routing_code, e.iban, start.isoformat(), end.isoformat(),
                     f"{s.days_payable:.0f}", f"{fixed:.2f}", f"{variable:.2f}", "0"])
        total += s.net
        count += 1
    from django.utils import timezone

    now = timezone.localtime()
    rows.append(["SCR", company.employer_eid, company.employer_bank_routing, now.strftime("%Y-%m-%d"),
                 now.strftime("%H%M"), f"{run.month:02d}{run.year}", str(count), f"{total:.2f}", "AED", run.number])
    return rows
