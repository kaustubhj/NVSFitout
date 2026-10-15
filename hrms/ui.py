import csv

from django.core.exceptions import ValidationError
from django.http import HttpResponse

from core.ui import Action, Inline, Related, Screen, register
from core.workflow import open_detail, set_status

from . import services
from .models import (AgencySupplier, Attendance, AttendanceSheet, Camp, Deduction, Department, Designation, Employee,
                     EmployeeDocument, LeaveApplication, LeaveType, Loan, Mobilization, MobilizationLine, PayrollRun,
                     Payslip, PayslipCost, PublicHoliday, Room, RoomAllocation, Trade, VisaQuota)

M = "hrms"
st = lambda *s: (lambda o: o.status in s)  # noqa: E731


# --- actions -------------------------------------------------------------------

def mob_confirm(request, mob):
    from projects.models import ManpowerAllocation

    if not mob.lines.exists():
        raise ValidationError("Add employees to mobilize.")
    for l in mob.lines.select_related("employee"):
        ManpowerAllocation.objects.get_or_create(project=mob.project, employee=l.employee, date_from=mob.date_from,
                                                 defaults={"trade": l.trade or l.employee.primary_trade,
                                                           "date_to": mob.date_to, "role": mob.job})
    set_status(mob, "confirmed")
    return f"{mob.lines.count()} employee(s) mobilized to {mob.project.code}."


def mob_attendance(request, mob):
    sheet = AttendanceSheet.objects.create(project=mob.project, date=mob.date_from)
    for l in mob.lines.select_related("employee__primary_trade"):
        trade = l.trade or l.employee.primary_trade
        Attendance.objects.create(sheet=sheet, employee=l.employee, trade=trade,
                                  hours_worked=trade.standard_hours if trade else 8)
    sheet.recalc()
    return open_detail(request, sheet, "Attendance sheet created from the mobilization; adjust hours and confirm OT.")


def sheet_confirm(request, sheet):
    sheet.recalc()
    set_status(sheet, "confirmed")
    return "Overtime confirmed by the Fit-Out team; it will be paid in payroll."


def sheet_reopen(request, sheet):
    set_status(sheet, "draft")


def leave_approve(request, lv):
    lv.recalc()
    set_status(lv, "approved")


def leave_reject(request, lv):
    set_status(lv, "rejected")


def leave_taken(request, lv):
    set_status(lv, "taken")


def loan_disburse(request, loan):
    from accounts.services import ctl, post_journal

    c = ctl()
    post_journal(loan.date, [
        {"account": c.require("employee_loans"), "debit": loan.amount, "employee": loan.employee},
        {"account": c.require("cash"), "credit": loan.amount, "description": f"{loan.get_loan_type_display()} {loan.employee}"},
    ], "PV", f"{loan.get_loan_type_display()} to {loan.employee}", source=loan)
    set_status(loan, "active")


def payroll_process(request, run):
    n = services.process_payroll(run)
    return f"Payroll processed for {n} employee(s)."


def payroll_post(request, run):
    entry = services.post_payroll(run)
    return f"Payroll posted to the GL ({entry.number if entry else 'nothing to post'})."


def payroll_paid(request, run):
    from accounts.models import BankAccount
    from accounts.services import ctl, post_journal

    bank = BankAccount.objects.first()
    if bank is None:
        raise ValidationError("Set up a bank account first.")
    post_journal(run.date, [
        {"account": ctl().require("payroll_payable"), "debit": run.total_net, "description": "WPS salary transfer"},
        {"account": bank.account, "credit": run.total_net, "description": f"WPS {run.month:02d}/{run.year}"},
    ], "PV", f"Salary payment {run}", source=run)
    set_status(run, "paid")
    return "Salary transfer posted. Cash OT remains payable until paid out."


def payroll_wps(request, run):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="WPS_{run.year}{run.month:02d}_{run.number}.csv"'
    w = csv.writer(resp)
    for row in services.wps_rows(run):
        w.writerow(row)
    return resp


# --- screens -------------------------------------------------------------------

class Master(Screen):
    list_filters = ()

    def editable(self, obj):
        return True


@register(M)
class EmployeeScreen(Master):
    model = Employee
    slug = "employees"
    list_display = ("code", "name", "employee_type", "designation", "primary_trade", "department", "basic_salary", "status")
    search_fields = ("code", "name", "wps_person_id", "nationality")
    list_filters = ("employee_type", "status", "department", "primary_trade")
    inlines = (Inline(EmployeeDocument, ("doc_type", "number", "issue_date", "expiry_date", "file"), extra=1,
                      title="Employee documents"),)
    related = (
        Related("Room allocation", lambda o: o.room_allocations.all(), ("room", "date_from", "date_to")),
        Related("Leave", lambda o: o.leaves.all()[:10], ("number", "leave_type", "date_from", "date_to", "status")),
        Related("Loans & advances", lambda o: o.loans.all(), ("number", "loan_type", "amount", ("Balance", "balance"), "status")),
        Related("Payslips", lambda o: o.payslips.select_related("run")[:12], ("run", "gross", "net")),
    )


@register(M)
class MobScreen(Screen):
    model = Mobilization
    slug = "mobilization"
    title = "Mobilization"
    list_display = ("number", "date", "project", "kind", "job", "date_from", "date_to", "status")
    list_filters = ("status", "project", "kind")
    form_fields = ("date", "project", "kind", "job", "date_from", "date_to", "remarks")
    inlines = (Inline(MobilizationLine, ("employee", "trade"), extra=6, title="Employees (bulk)"),)
    actions = (
        Action("confirm", "Confirm mobilization", mob_confirm, st("draft"), style="success"),
        Action("attendance", "+ Attendance sheet", mob_attendance, st("confirmed")),
    )


@register(M)
class SheetScreen(Screen):
    model = AttendanceSheet
    slug = "attendance"
    title = "Attendance & Overtime"
    help_text = "Manual attendance per project and day. OT is computed by trade hours: normal 1.25×, Friday and public holiday at their own rates."
    list_display = ("number", "date", "project", "status")
    list_filters = ("status", "project")
    form_fields = ("date", "project", "remarks")
    inlines = (Inline(Attendance, ("employee", "trade", "status", "hours_worked"), extra=8, title="Attendance",
                      display=("employee", "trade", "status", "hours_worked", "normal_hours", "normal_ot", "friday_ot",
                               "holiday_ot"), totals=("hours_worked", "normal_ot", "friday_ot", "holiday_ot")),)
    actions = (
        Action("confirm", "Confirm OT (Fit-Out team)", sheet_confirm, st("draft"), style="success"),
        Action("reopen", "Reopen", sheet_reopen, st("confirmed"), style="ghost", groups=["HR"]),
    )


@register(M)
class LeaveScreen(Screen):
    model = LeaveApplication
    slug = "leave"
    title = "Leave"
    list_display = ("number", "employee", "leave_type", "date_from", "date_to", ("Days", "days"),
                    "leave_salary_in_advance", "status")
    list_filters = ("status", "leave_type")
    form_fields = ("date", "employee", "leave_type", "date_from", "date_to", "leave_salary_in_advance", "remarks")
    detail_fields = ("number", "date", "employee", "leave_type", "date_from", "date_to", ("Days", "days"),
                     "leave_salary_in_advance", "leave_salary_amount", "paid_in_payroll", "status", "remarks")
    actions = (
        Action("approve", "Approve", leave_approve, st("draft"), style="success", groups=["HR", "Project Manager"]),
        Action("reject", "Reject", leave_reject, st("draft"), style="danger", groups=["HR", "Project Manager"]),
        Action("taken", "Mark taken", leave_taken, st("approved"), style="ghost"),
    )


@register(M)
class LoanScreen(Screen):
    model = Loan
    slug = "loans"
    title = "Loans & Advances"
    list_display = ("number", "date", "employee", "loan_type", "amount", "monthly_installment", ("Balance", "balance"), "status")
    list_filters = ("status", "loan_type")
    form_fields = ("date", "employee", "loan_type", "amount", "monthly_installment", "remarks")
    actions = (Action("disburse", "Disburse", loan_disburse, st("draft"), style="success",
                      confirm="Pay out the loan / advance from cash?"),)


@register(M)
class DeductionScreen(Master):
    model = Deduction
    slug = "deductions"
    title = "Deductions (fines, food, advances)"
    list_display = ("employee", "deduction_type", "month", "year", "amount", "description", "payroll")
    list_filters = ("deduction_type",)
    search_fields = ("employee__name",)


@register(M)
class PayrollScreen(Screen):
    model = PayrollRun
    slug = "payroll"
    title = "Payroll Runs"
    list_display = ("number", "month", "year", "employee_type", "total_gross", "total_deductions", "total_net",
                    "total_cash_ot", "status")
    form_fields = ("date", "year", "month", "employee_type", "remarks")
    inlines = (Inline(Payslip, ("employee",), extra=0, title="Payslips", readonly=True,
                      display=("employee", "days_payable", "basic", "allowances", "normal_ot_hours", "friday_ot_hours",
                               "holiday_ot_hours", "ot_amount", "cash_ot_amount", "leave_salary",
                               "unpaid_leave_deduction", "food_deduction", "loan_recovery", "other_deductions", "net"),
                      totals=("basic", "allowances", "ot_amount", "cash_ot_amount", "leave_salary", "food_deduction",
                              "loan_recovery", "other_deductions", "net")),)
    actions = (
        Action("process", "Process payroll", payroll_process, st("draft", "processed")),
        Action("post", "Post to GL", payroll_post, st("processed"), style="success",
               confirm="Post salary cost by project to the general ledger?"),
        Action("wps", "Download WPS file", payroll_wps, st("processed", "posted", "paid"), style="ghost"),
        Action("paid", "Mark paid (WPS transfer)", payroll_paid, st("posted"), style="success"),
    )
    related = (Related("Cost allocation by project",
                       lambda o: PayslipCost.objects.filter(payslip__run=o).select_related("payslip__employee", "project"),
                       ("payslip__employee", "project", "hours", "amount")),)
    print_template = "print/payslips.html"

    def editable(self, obj):
        return obj.status in ("draft", "processed")


@register(M)
class CampScreen(Master):
    model = Camp
    slug = "camps"
    list_display = ("name", "location", ("Capacity", "capacity"), ("Occupied", "occupied"))
    inlines = (Inline(Room, ("number", "capacity"), extra=3, title="Rooms"),)


@register(M)
class RoomAllocScreen(Master):
    model = RoomAllocation
    slug = "room-allocation"
    title = "Room Allocation"
    list_display = ("employee", "room", "date_from", "date_to")
    search_fields = ("employee__name", "room__number")

    def setup_form(self, form, request, obj):
        if "room" in form.fields:
            form.fields["room"].label_from_instance = lambda r: f"{r} ({r.occupied}/{r.capacity})"


@register(M)
class VisaScreen(Master):
    model = VisaQuota
    slug = "visas"
    title = "Visa Allocation"
    list_display = ("establishment", "designation", "quota", ("Used", "used"), "notes")
    related = (Related("Employees on this quota", lambda o: o.employees.all(), ("code", "name", "status")),)


@register(M)
class DepartmentScreen(Master):
    model = Department
    slug = "departments"
    list_display = ("name", "parent", "head")


@register(M)
class DesignationScreen(Master):
    model = Designation
    slug = "designations"
    title = "Designations & Job Descriptions"
    list_display = ("name", "job_description")


@register(M)
class TradeScreen(Master):
    model = Trade
    slug = "trades"
    list_display = ("name", "standard_hours", "labour_rate")


@register(M)
class HolidayScreen(Master):
    model = PublicHoliday
    slug = "holidays"
    title = "Public Holidays"
    list_display = ("date", "name")


@register(M)
class LeaveTypeScreen(Master):
    model = LeaveType
    slug = "leave-types"
    title = "Leave Types"
    list_display = ("name", "paid", "annual_entitlement_days", "is_annual_leave")


@register(M)
class AgencyScreen(Master):
    model = AgencySupplier
    slug = "agencies"
    title = "Manpower Agencies"
    list_display = ("name", "vendor")
