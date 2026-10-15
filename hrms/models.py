from decimal import Decimal

from django.db import models
from django.db.models import Sum

from core.models import ZERO, Doc, money_field, today


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    head = models.ForeignKey("Employee", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    def __str__(self):
        return self.name


class Designation(models.Model):
    name = models.CharField(max_length=100, unique=True)
    job_description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Trade(models.Model):
    name = models.CharField(max_length=100, unique=True)
    standard_hours = models.DecimalField("Normal working hours / day", max_digits=4, decimal_places=2, default=Decimal("8"))
    labour_rate = money_field(help_text="Costing rate per hour (hired labour)")

    def __str__(self):
        return self.name


class PublicHoliday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.name}"


class AgencySupplier(models.Model):
    name = models.CharField(max_length=150)
    vendor = models.ForeignKey("procurement.Vendor", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "manpower agency"

    def __str__(self):
        return self.name


class Camp(models.Model):
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name

    @property
    def capacity(self):
        return self.rooms.aggregate(c=Sum("capacity"))["c"] or 0

    @property
    def occupied(self):
        return RoomAllocation.objects.filter(room__camp=self, date_to__isnull=True).count()


class Room(models.Model):
    camp = models.ForeignKey(Camp, on_delete=models.CASCADE, related_name="rooms")
    number = models.CharField(max_length=20)
    capacity = models.PositiveIntegerField(default=8)

    class Meta:
        unique_together = [("camp", "number")]

    def __str__(self):
        return f"{self.camp.name} / {self.number}"

    @property
    def occupied(self):
        return self.allocations.filter(date_to__isnull=True).count()


class VisaQuota(models.Model):
    establishment = models.CharField("Establishment / company", max_length=150)
    designation = models.ForeignKey(Designation, null=True, blank=True, on_delete=models.SET_NULL)
    quota = models.PositiveIntegerField()
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "visa quota"

    def __str__(self):
        return f"{self.establishment} · {self.designation or 'any'} ({self.quota})"

    @property
    def used(self):
        return self.employees.filter(status="active").count()


class Employee(models.Model):
    TYPES = [("direct", "Direct (Fit-Out)"), ("hired", "Hired / agency")]
    STATUS = [("active", "Active"), ("on_leave", "On leave"), ("resigned", "Resigned"), ("terminated", "Terminated")]
    TICKET = [("none", "None"), ("A", "Category A (annual, family)"), ("B", "Category B (annual)"),
              ("C", "Category C (every 2 years)")]
    code = models.CharField("Employee no.", max_length=20, unique=True)
    name = models.CharField(max_length=150)
    employee_type = models.CharField(max_length=10, choices=TYPES, default="direct")
    agency = models.ForeignKey(AgencySupplier, null=True, blank=True, on_delete=models.SET_NULL)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL)
    designation = models.ForeignKey(Designation, null=True, blank=True, on_delete=models.SET_NULL)
    primary_trade = models.ForeignKey(Trade, null=True, blank=True, on_delete=models.SET_NULL, related_name="primary_employees")
    trades = models.ManyToManyField(Trade, blank=True, related_name="employees", verbose_name="All trades")
    nationality = models.CharField(max_length=60, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    joining_date = models.DateField(default=today)
    leaving_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    basic_salary = money_field()
    housing_allowance = money_field()
    transport_allowance = money_field()
    other_allowance = money_field()
    food_deduction = money_field(help_text="Monthly food deduction")
    hourly_rate = money_field(help_text="For hired labour paid per hour")
    ot_eligible = models.BooleanField("OT eligible", default=True)
    cash_ot = models.BooleanField("Cash OT (paid outside WPS salary)", default=False)
    ticket_category = models.CharField(max_length=5, choices=TICKET, default="none")
    ticket_amount = money_field(help_text="Ticket entitlement per eligible period")
    bank_name = models.CharField(max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    bank_routing_code = models.CharField(max_length=20, blank=True)
    wps_person_id = models.CharField("Labour card / WPS person ID", max_length=30, blank=True)
    visa_quota = models.ForeignKey(VisaQuota, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees",
                                   verbose_name="Visa allocation")
    status = models.CharField(max_length=20, choices=STATUS, default="active")

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def gross_salary(self):
        return self.basic_salary + self.housing_allowance + self.transport_allowance + self.other_allowance

    def daily_basic(self):
        return self.basic_salary * 12 / 365

    def hourly_basic(self, trade_hours=Decimal("8")):
        if self.employee_type == "hired" and self.hourly_rate:
            return self.hourly_rate
        return self.basic_salary * 12 / 365 / trade_hours

    def standard_hours(self):
        return self.primary_trade.standard_hours if self.primary_trade else Decimal("8")

    def current_room(self):
        alloc = self.room_allocations.filter(date_to__isnull=True).select_related("room").first()
        return alloc.room if alloc else None


class EmployeeDocument(models.Model):
    TYPES = [("passport", "Passport"), ("visa", "Residence visa"), ("eid", "Emirates ID"),
             ("labour_card", "Labour card"), ("contract", "Labour contract"), ("medical", "Medical insurance"),
             ("certificate", "Trade certificate"), ("other", "Other")]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=TYPES)
    number = models.CharField(max_length=60, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    file = models.FileField(upload_to="employee_docs/", blank=True)


class RoomAllocation(models.Model):
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="allocations")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="room_allocations")
    date_from = models.DateField(default=today)
    date_to = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.employee} → {self.room}"


class Mobilization(Doc):
    SEQ_KEY, SEQ_PREFIX = "MOB", "MOB-"
    KINDS = [("daily", "Daily"), ("bulk", "Bulk / period")]
    STATUS = [("draft", "Draft"), ("confirmed", "Confirmed")]
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=KINDS, default="bulk")
    job = models.CharField("Job / work area", max_length=150, blank=True)
    date_from = models.DateField(default=today)
    date_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")


class MobilizationLine(models.Model):
    mobilization = models.ForeignKey(Mobilization, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    trade = models.ForeignKey(Trade, null=True, blank=True, on_delete=models.SET_NULL)


class AttendanceSheet(Doc):
    """Manual attendance (no device) for one project and day."""

    SEQ_KEY, SEQ_PREFIX = "ATT", "ATT-"
    STATUS = [("draft", "Draft"), ("confirmed", "OT confirmed by Fit-Out team")]
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def recalc(self):
        for line in self.lines.all():
            line.compute_ot()
            line.save()


class Attendance(models.Model):
    STATUS = [("P", "Present"), ("A", "Absent"), ("L", "On leave"), ("H", "Holiday / weekly off")]
    sheet = models.ForeignKey(AttendanceSheet, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance")
    trade = models.ForeignKey(Trade, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=1, choices=STATUS, default="P")
    hours_worked = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("8"))
    normal_hours = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO, editable=False)
    normal_ot = models.DecimalField("Normal OT hrs", max_digits=5, decimal_places=2, default=ZERO, editable=False)
    friday_ot = models.DecimalField("Friday OT hrs", max_digits=5, decimal_places=2, default=ZERO, editable=False)
    holiday_ot = models.DecimalField("Holiday OT hrs", max_digits=5, decimal_places=2, default=ZERO, editable=False)

    class Meta:
        verbose_name_plural = "attendance"

    def compute_ot(self):
        date = self.sheet.date
        trade = self.trade or self.employee.primary_trade
        std = trade.standard_hours if trade else Decimal("8")
        self.normal_hours = self.normal_ot = self.friday_ot = self.holiday_ot = ZERO
        if self.status != "P":
            return
        hours = self.hours_worked
        if PublicHoliday.objects.filter(date=date).exists():
            self.holiday_ot = hours if self.employee.ot_eligible else ZERO
        elif date.weekday() == 4:  # Friday
            self.friday_ot = hours if self.employee.ot_eligible else ZERO
        else:
            self.normal_hours = min(hours, std)
            self.normal_ot = max(hours - std, ZERO) if self.employee.ot_eligible else ZERO


class LeaveType(models.Model):
    name = models.CharField(max_length=60)
    paid = models.BooleanField(default=True)
    annual_entitlement_days = models.PositiveIntegerField(default=30)
    is_annual_leave = models.BooleanField(default=False, help_text="Leave salary is paid for annual leave")

    def __str__(self):
        return self.name


class LeaveApplication(Doc):
    SEQ_KEY, SEQ_PREFIX = "LV", "LV-"
    STATUS = [("draft", "Draft"), ("approved", "Approved"), ("rejected", "Rejected"), ("taken", "Taken")]
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leaves")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    date_from = models.DateField()
    date_to = models.DateField()
    leave_salary_in_advance = models.BooleanField(default=False)
    leave_salary_amount = money_field(editable=False)
    paid_in_payroll = models.ForeignKey("PayrollRun", null=True, blank=True, on_delete=models.SET_NULL, editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    @property
    def days(self):
        return (self.date_to - self.date_from).days + 1

    def recalc(self):
        if self.leave_type.is_annual_leave:
            # leave salary = (basic + housing) / 30 × days (default method; configurable)
            daily = (self.employee.basic_salary + self.employee.housing_allowance) / 30
            self.leave_salary_amount = round(daily * self.days, 2)
        else:
            self.leave_salary_amount = ZERO
        self.save(update_fields=["leave_salary_amount"])


class Loan(Doc):
    SEQ_KEY, SEQ_PREFIX = "LN", "LN-"
    TYPES = [("loan", "Loan"), ("advance", "Salary advance")]
    STATUS = [("draft", "Draft"), ("active", "Active (disbursed)"), ("closed", "Closed")]
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="loans")
    loan_type = models.CharField(max_length=10, choices=TYPES, default="loan")
    amount = money_field()
    monthly_installment = money_field()
    recovered = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    @property
    def balance(self):
        return self.amount - self.recovered


class Deduction(models.Model):
    TYPES = [("fine", "Fine"), ("food", "Food"), ("advance", "Advance salary"), ("damage", "Damage / loss"),
             ("other", "Other")]
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="deductions")
    deduction_type = models.CharField(max_length=10, choices=TYPES)
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    amount = money_field()
    description = models.CharField(max_length=200, blank=True)
    payroll = models.ForeignKey("PayrollRun", null=True, blank=True, on_delete=models.SET_NULL, editable=False)

    def __str__(self):
        return f"{self.employee} {self.get_deduction_type_display()} {self.amount}"


class PayrollRun(Doc):
    SEQ_KEY, SEQ_PREFIX = "PAY", "PAY-"
    STATUS = [("draft", "Draft"), ("processed", "Processed"), ("posted", "Posted to GL"), ("paid", "Paid")]
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    employee_type = models.CharField(max_length=10, choices=[("all", "All")] + Employee.TYPES, default="all")
    total_gross = money_field(editable=False)
    total_deductions = money_field(editable=False)
    total_net = money_field(editable=False)
    total_cash_ot = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def __str__(self):
        return f"{self.number} · {self.month:02d}/{self.year}"


class Payslip(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="payslips")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payslips")
    days_payable = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    basic = money_field()
    allowances = money_field()
    normal_ot_hours = models.DecimalField(max_digits=7, decimal_places=2, default=ZERO)
    friday_ot_hours = models.DecimalField(max_digits=7, decimal_places=2, default=ZERO)
    holiday_ot_hours = models.DecimalField(max_digits=7, decimal_places=2, default=ZERO)
    ot_amount = money_field()
    cash_ot_amount = money_field(help_text="Kept out of the WPS salary")
    leave_salary = money_field()
    food_deduction = money_field()
    loan_recovery = money_field()
    other_deductions = money_field()
    unpaid_leave_deduction = money_field()
    gross = money_field()
    net = money_field()

    class Meta:
        ordering = ["employee__code"]

    def __str__(self):
        return f"{self.run} · {self.employee}"


class PayslipCost(models.Model):
    """Payroll cost allocation by project (from attendance hours)."""

    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name="costs")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    hours = models.DecimalField(max_digits=7, decimal_places=2, default=ZERO)
    amount = money_field()
