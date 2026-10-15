from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Sum

from core.models import ZERO, Doc, money_field, today
from core.services import q2


class Account(models.Model):
    TYPES = [("asset", "Asset"), ("liability", "Liability"), ("equity", "Equity"), ("income", "Income"),
             ("expense", "Expense")]
    COST_CATEGORIES = [("", "—"), ("material", "Material"), ("labour", "Labour"), ("subcontract", "Subcontract"),
                       ("overhead", "Overhead"), ("other", "Other direct")]
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    type = models.CharField(max_length=10, choices=TYPES)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    is_group = models.BooleanField(default=False, help_text="Group accounts cannot be posted to")
    cost_category = models.CharField(max_length=15, choices=COST_CATEGORIES, blank=True,
                                     help_text="Used for project costing (expense accounts)")
    is_direct_cost = models.BooleanField(default=False, help_text="Counts toward gross profit")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "GL account"
        verbose_name_plural = "chart of accounts"

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def debit_normal(self):
        return self.type in ("asset", "expense")

    def balance(self, date_to=None, date_from=None, project=None):
        qs = self.lines.filter(entry__status="posted")
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if project:
            qs = qs.filter(project=project)
        agg = qs.aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
        d, c = agg["d"] or ZERO, agg["c"] or ZERO
        return d - c if self.debit_normal else c - d


class ControlAccounts(models.Model):
    """Which GL accounts automatic postings use."""

    names = [
        ("receivable", "Accounts receivable"), ("payable", "Accounts payable"),
        ("grni", "Goods received not invoiced"), ("inventory", "Inventory (default)"),
        ("vat_output", "VAT output"), ("vat_input", "VAT input"),
        ("retention_receivable", "Retention receivable"), ("customer_advance", "Customer advances"),
        ("contract_revenue", "Contract revenue"), ("payroll_payable", "Payroll payable"),
        ("labour_cost", "Labour cost (direct)"), ("staff_cost", "Staff salaries (overhead)"),
        ("material_cost", "Material cost (default)"), ("subcontract_cost", "Subcontract cost (default)"),
        ("pdc_receivable", "PDC receivable"), ("pdc_payable", "PDC payable"),
        ("stock_adjustment", "Stock adjustment / shrinkage"), ("landed_cost_clearing", "Landed cost clearing"),
        ("price_variance", "Purchase price variance"), ("depreciation_expense", "Depreciation expense"),
        ("employee_loans", "Employee loans & advances"), ("cash", "Cash in hand"),
        ("retained_earnings", "Retained earnings"), ("exchange_difference", "Exchange difference"),
        ("payroll_recoveries", "Payroll recoveries (food, fines)"),
    ]
    receivable = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    payable = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    grni = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+", verbose_name="GRNI")
    inventory = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    vat_output = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    vat_input = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    retention_receivable = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    customer_advance = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    contract_revenue = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    payroll_payable = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    labour_cost = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    staff_cost = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    material_cost = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    subcontract_cost = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    pdc_receivable = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                       verbose_name="PDC receivable")
    pdc_payable = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                    verbose_name="PDC payable")
    stock_adjustment = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    landed_cost_clearing = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    price_variance = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    depreciation_expense = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    employee_loans = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cash = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    retained_earnings = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    exchange_difference = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    payroll_recoveries = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "control account mapping"
        verbose_name_plural = "control account mapping"

    def __str__(self):
        return "Control account mapping"

    @classmethod
    def get(cls):
        return cls.objects.first() or cls.objects.create()

    def require(self, name):
        acc = getattr(self, name)
        if acc is None:
            from django.core.exceptions import ValidationError

            raise ValidationError(f"Control account '{name}' is not mapped. Set it under Accounts → Control accounts.")
        return acc


class JournalEntry(Doc):
    SEQ_KEY, SEQ_PREFIX = "JV", "JV-"
    VOUCHER_TYPES = [("JV", "Journal voucher"), ("PV", "Payment voucher"), ("RV", "Receipt voucher"),
                     ("CV", "Contra voucher"), ("SI", "Sales invoice"), ("PI", "Purchase invoice"),
                     ("PAY", "Payroll"), ("DEP", "Depreciation"), ("STK", "Stock"), ("OB", "Opening balance")]
    STATUS = [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")]
    voucher_type = models.CharField(max_length=4, choices=VOUCHER_TYPES, default="JV")
    reference = models.CharField(max_length=80, blank=True)
    narration = models.CharField(max_length=300, blank=True)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1"))
    total = money_field(editable=False)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL, editable=False)
    object_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    source = GenericForeignKey("content_type", "object_id")
    reversal_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, editable=False,
                                    related_name="reversals")
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "journal voucher"
        verbose_name_plural = "journal vouchers"
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.SEQ_KEY = self.voucher_type
            self.SEQ_PREFIX = f"{self.voucher_type}-"
        super().save(*args, **kwargs)

    def recalc(self):
        rate = self.exchange_rate or Decimal("1")
        for line in self.lines.all():
            line.base_debit = q2(line.debit * rate)
            line.base_credit = q2(line.credit * rate)
            line.save(update_fields=["base_debit", "base_credit"])
        self.total = self.lines.aggregate(t=Sum("base_debit"))["t"] or ZERO
        self.save(update_fields=["total"])

    @property
    def source_doc(self):
        return self.source


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines", limit_choices_to={"is_group": False})
    description = models.CharField(max_length=200, blank=True)
    debit = money_field()
    credit = money_field()
    base_debit = money_field(editable=False)
    base_credit = money_field(editable=False)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="journal_lines")
    customer = models.ForeignKey("sales.Customer", null=True, blank=True, on_delete=models.PROTECT)
    vendor = models.ForeignKey("procurement.Vendor", null=True, blank=True, on_delete=models.PROTECT)
    employee = models.ForeignKey("hrms.Employee", null=True, blank=True, on_delete=models.PROTECT)
    reconciled = models.BooleanField(default=False, editable=False)

    def __str__(self):
        return f"{self.entry.number} {self.account.code} Dr {self.base_debit} Cr {self.base_credit}"


class BankAccount(models.Model):
    name = models.CharField(max_length=100)
    account = models.OneToOneField(Account, on_delete=models.PROTECT, verbose_name="GL account")
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=40, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    swift = models.CharField("SWIFT", max_length=15, blank=True)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    next_cheque_no = models.PositiveIntegerField(default=100001)

    def __str__(self):
        return self.name


class BankStatementLine(models.Model):
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name="statement_lines")
    date = models.DateField()
    description = models.CharField(max_length=250)
    reference = models.CharField(max_length=80, blank=True)
    amount = money_field(help_text="+ deposit, − withdrawal")
    matched_line = models.OneToOneField(JournalLine, null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name="statement_line")

    class Meta:
        ordering = ["date", "id"]


class CustomerInvoice(Doc):
    SEQ_KEY, SEQ_PREFIX = "INV", "INV-"
    TYPES = [("advance", "Advance"), ("progress", "Progressive"), ("final", "Final"),
             ("retention", "Retention release"), ("other", "Other / service")]
    STATUS = [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")]
    customer = models.ForeignKey("sales.Customer", on_delete=models.PROTECT)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="customer_invoices")
    contract = models.ForeignKey("sales.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="invoices")
    invoice_type = models.CharField(max_length=10, choices=TYPES, default="progress")
    cumulative_percent = models.DecimalField("Cumulative % complete", max_digits=6, decimal_places=2, null=True, blank=True,
                                             help_text="Progress / final: work certified to date as % of revised contract value")
    description = models.CharField(max_length=250, blank=True)
    gross_amount = money_field(help_text="Work value of this invoice (auto from % for progress / final)")
    advance_recovery = money_field(editable=False)
    retention_amount = money_field(editable=False)
    vat_amount = money_field(editable=False)
    total = money_field("Net receivable", editable=False)
    due_date = models.DateField(null=True, blank=True)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1"))
    paid_amount = money_field(editable=False)
    journal = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "customer invoice"
        ordering = ["-date", "-id"]

    @property
    def balance(self):
        return self.total - self.paid_amount

    def previous(self):
        return CustomerInvoice.objects.filter(contract=self.contract, status="posted").exclude(pk=self.pk)

    def recalc(self):
        from core.models import Company

        company = Company.get()
        if self.contract_id and not self.project_id:
            self.project = self.contract.projects.first()
        if self.contract_id:
            self.customer = self.contract.customer
        if self.due_date is None:
            from datetime import timedelta

            self.due_date = self.date + timedelta(days=self.customer.credit_days)
        contract = self.contract
        self.advance_recovery = self.retention_amount = ZERO
        if contract and self.invoice_type == "advance" and not self.gross_amount:
            self.gross_amount = q2(contract.contract_value * contract.advance_percent / 100)
        if contract and self.invoice_type in ("progress", "final"):
            value = contract.revised_value
            if self.invoice_type == "final" and self.cumulative_percent is None:
                self.cumulative_percent = Decimal("100")
            if self.cumulative_percent is not None:
                certified_before = self.previous().filter(invoice_type__in=["progress", "final"]).aggregate(
                    t=Sum("gross_amount"))["t"] or ZERO
                self.gross_amount = q2(value * self.cumulative_percent / 100) - certified_before
            advance_total = self.previous().filter(invoice_type="advance").aggregate(t=Sum("gross_amount"))["t"] or ZERO
            recovered = self.previous().aggregate(t=Sum("advance_recovery"))["t"] or ZERO
            remaining = advance_total - recovered
            if self.invoice_type == "final":
                self.advance_recovery = remaining
            else:
                self.advance_recovery = min(q2(self.gross_amount * contract.advance_percent / 100), remaining)
            self.retention_amount = q2(self.gross_amount * contract.retention_percent / 100)
        if self.invoice_type == "retention":
            self.vat_amount = ZERO
        else:
            self.vat_amount = q2((self.gross_amount - self.advance_recovery) * company.vat_percent / 100)
        self.total = self.gross_amount - self.advance_recovery - self.retention_amount + self.vat_amount
        self.save()

    @property
    def retention_due_date(self):
        from datetime import timedelta

        from core.models import Company

        if self.invoice_type != "final":
            return None
        return self.date + timedelta(days=Company.get().retention_due_days)


class Receipt(Doc):
    SEQ_KEY, SEQ_PREFIX = "RCT", "RV-"
    MODES = [("transfer", "Bank transfer"), ("cheque", "Cheque (current)"), ("pdc", "Post-dated cheque"), ("cash", "Cash")]
    STATUS = [("draft", "Draft"), ("posted", "Posted"), ("pdc", "PDC in hand"), ("cleared", "PDC cleared"),
              ("bounced", "Bounced"), ("cancelled", "Cancelled")]
    customer = models.ForeignKey("sales.Customer", on_delete=models.PROTECT)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    mode = models.CharField(max_length=10, choices=MODES, default="transfer")
    bank_account = models.ForeignKey(BankAccount, null=True, blank=True, on_delete=models.PROTECT)
    amount = money_field()
    cheque_no = models.CharField(max_length=30, blank=True)
    cheque_date = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    @property
    def allocated(self):
        return self.allocations.aggregate(t=Sum("amount"))["t"] or ZERO


class ReceiptAllocation(models.Model):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(CustomerInvoice, on_delete=models.PROTECT, related_name="allocations",
                                limit_choices_to={"status": "posted"})
    amount = money_field()


class VendorInvoice(Doc):
    SEQ_KEY, SEQ_PREFIX = "VINV", "PI-"
    STATUS = [("draft", "Draft"), ("matched", "3-way matched"), ("discrepancy", "Discrepancy"),
              ("posted", "Posted"), ("cancelled", "Cancelled")]
    vendor = models.ForeignKey("procurement.Vendor", on_delete=models.PROTECT)
    purchase_order = models.ForeignKey("procurement.PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="vendor_invoices")
    vendor_invoice_no = models.CharField(max_length=60)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT)
    due_date = models.DateField(null=True, blank=True)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1"))
    subtotal = money_field(editable=False)
    vat_amount = money_field("VAT")
    total = money_field(editable=False)
    paid_amount = money_field(editable=False)
    match_notes = models.TextField(blank=True, editable=False)
    discrepancy_approved = models.BooleanField(default=False, editable=False)
    journal = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "vendor invoice"
        ordering = ["-date", "-id"]

    @property
    def balance(self):
        return self.total - self.paid_amount

    def recalc(self):
        from datetime import timedelta

        from core.models import Company

        self.subtotal = self.lines.aggregate(t=Sum("amount"))["t"] or ZERO
        if not self.vat_amount:
            self.vat_amount = q2(self.subtotal * Company.get().vat_percent / 100)
        self.total = self.subtotal + self.vat_amount
        if self.due_date is None:
            self.due_date = self.date + timedelta(days=self.vendor.credit_days)
        if self.purchase_order_id and not self.project_id:
            self.project = self.purchase_order.project
        self.save()


class VendorInvoiceLine(models.Model):
    invoice = models.ForeignKey(VendorInvoice, on_delete=models.CASCADE, related_name="lines")
    po_line = models.ForeignKey("procurement.PurchaseOrderLine", null=True, blank=True, on_delete=models.PROTECT)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT,
                                help_text="Expense account for lines without a PO", limit_choices_to={"is_group": False})
    description = models.CharField(max_length=200, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("1"))
    rate = money_field(decimal_places=4)
    amount = money_field(editable=False)
    match_result = models.CharField(max_length=200, blank=True, editable=False)

    def save(self, *args, **kwargs):
        self.amount = q2(self.qty * self.rate)
        super().save(*args, **kwargs)


class VendorPayment(Doc):
    SEQ_KEY, SEQ_PREFIX = "VPAY", "PV-"
    APPROVAL_DOC_TYPE = "vendor_payment"
    MODES = [("cheque", "Cheque"), ("pdc", "Post-dated cheque"), ("transfer", "Bank transfer"), ("cash", "Cash")]
    STATUS = [("draft", "Draft"), ("pending_approval", "Pending approval"), ("approved", "Approved"),
              ("posted", "Paid / posted"), ("cleared", "PDC cleared"), ("cancelled", "Cancelled")]
    vendor = models.ForeignKey("procurement.Vendor", on_delete=models.PROTECT)
    bank_account = models.ForeignKey(BankAccount, null=True, blank=True, on_delete=models.PROTECT)
    mode = models.CharField(max_length=10, choices=MODES, default="cheque")
    amount = money_field()
    cheque_no = models.CharField(max_length=30, blank=True)
    cheque_date = models.DateField(null=True, blank=True)
    payee_name = models.CharField(max_length=150, blank=True, help_text="Name printed on the cheque")
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def approval_amount(self):
        return self.amount


class VendorPaymentAllocation(models.Model):
    payment = models.ForeignKey(VendorPayment, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(VendorInvoice, on_delete=models.PROTECT, related_name="allocations",
                                limit_choices_to={"status": "posted"})
    amount = money_field()


class AssetCategory(models.Model):
    name = models.CharField(max_length=100)
    asset_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    accumulated_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                            verbose_name="Accumulated depreciation account")
    expense_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                        verbose_name="Depreciation expense account")
    useful_life_months = models.PositiveIntegerField(default=60)

    class Meta:
        verbose_name_plural = "asset categories"

    def __str__(self):
        return self.name


class FixedAsset(models.Model):
    STATUS = [("active", "Active"), ("disposed", "Disposed")]
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT)
    purchase_date = models.DateField()
    cost = money_field()
    salvage_value = money_field()
    useful_life_months = models.PositiveIntegerField(default=60)
    location = models.CharField(max_length=100, blank=True)
    registration_no = models.CharField("Plate / registration no.", max_length=40, blank=True)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL,
                                help_text="Charge depreciation to this project (e.g. site machinery)")
    status = models.CharField(max_length=10, choices=STATUS, default="active")

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def monthly_depreciation(self):
        if not self.useful_life_months:
            return ZERO
        return q2((self.cost - self.salvage_value) / self.useful_life_months)

    @property
    def accumulated_depreciation(self):
        return self.depreciation_lines.filter(run__status="posted").aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def net_book_value(self):
        return self.cost - self.accumulated_depreciation


class DepreciationRun(Doc):
    SEQ_KEY, SEQ_PREFIX = "DEP", "DR-"
    STATUS = [("draft", "Draft"), ("posted", "Posted")]
    period_end = models.DateField(help_text="Month-end date being depreciated")
    total = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")


class DepreciationLine(models.Model):
    run = models.ForeignKey(DepreciationRun, on_delete=models.CASCADE, related_name="lines")
    asset = models.ForeignKey(FixedAsset, on_delete=models.PROTECT, related_name="depreciation_lines")
    amount = money_field()


class Budget(models.Model):
    MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    fiscal_year = models.PositiveIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, limit_choices_to={"is_group": False})
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE)
    jan = money_field()
    feb = money_field()
    mar = money_field()
    apr = money_field()
    may = money_field()
    jun = money_field()
    jul = money_field()
    aug = money_field()
    sep = money_field()
    oct = money_field()
    nov = money_field()
    dec = money_field()

    class Meta:
        unique_together = [("fiscal_year", "account", "project")]

    def __str__(self):
        return f"{self.fiscal_year} {self.account}"

    @property
    def annual(self):
        return sum((getattr(self, m) for m in self.MONTHS), ZERO)

    def upto(self, month):
        return sum((getattr(self, m) for m in self.MONTHS[:month]), ZERO)


class Liability(models.Model):
    TYPES = [("loan", "Bank loan"), ("lease", "Lease"), ("overdraft", "Overdraft"), ("other", "Other")]
    name = models.CharField(max_length=150)
    liability_type = models.CharField(max_length=10, choices=TYPES, default="loan")
    lender = models.CharField(max_length=150, blank=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, limit_choices_to={"type": "liability"})
    principal = money_field()
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    start_date = models.DateField(default=today)
    end_date = models.DateField(null=True, blank=True)
    monthly_installment = money_field()

    class Meta:
        verbose_name_plural = "liabilities"

    def __str__(self):
        return self.name

    @property
    def outstanding(self):
        return self.account.balance()
