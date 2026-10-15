from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

from core.models import ZERO, Doc, money_field, qty_field
from core.services import q2


class Customer(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    trn = models.CharField("TRN", max_length=30, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    credit_days = models.PositiveIntegerField(default=30)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @classmethod
    def create_named(cls, name, **details):
        from core.services import next_number

        return cls.objects.create(code=next_number("CUST", "C-"), name=name, **details)


class Lead(Doc):
    SEQ_KEY, SEQ_PREFIX = "LEAD", "LD-"
    SOURCES = [("referral", "Referral"), ("website", "Website"), ("tender", "Tender portal"),
               ("existing", "Existing client"), ("consultant", "Consultant / architect"),
               ("walk_in", "Walk-in / call"), ("other", "Other")]
    STATUS = [("new", "New"), ("under_review", "Under review"), ("qualified", "Qualified"),
              ("rejected", "Rejected"), ("estimation", "In estimation"), ("quoted", "Quoted"),
              ("won", "Won"), ("lost", "Lost")]
    SALUTATIONS = [("Mr.", "Mr."), ("Mrs.", "Mrs."), ("Ms.", "Ms."), ("Miss.", "Miss."), ("Dr.", "Dr.")]
    salutation = models.CharField("Title", max_length=5, choices=SALUTATIONS, blank=True)
    full_name = models.CharField("Full name", max_length=150, blank=True)
    company = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    title = models.CharField("Subject / project", max_length=200)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT,
                                 help_text="Leave blank for a new prospect; a customer is created when the lead is qualified.")
    source = models.CharField("Lead source", max_length=20, choices=SOURCES, default="referral")
    location = models.CharField(max_length=200, blank=True)
    scope = models.TextField("Scope of work", blank=True)
    expected_value = money_field()
    capability_review = models.TextField(blank=True, help_text="Scope reviewed against company capability")
    salesperson = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField("Lead status", max_length=20, choices=STATUS, default="new")

    def __str__(self):
        return f"{self.number} · {self.title}"

    @property
    def contact_name(self):
        return " ".join(x for x in (self.salutation, self.full_name) if x)

    def customer_details(self):
        return {"contact_person": self.contact_name, "phone": self.mobile, "email": self.email}

    def ensure_customer(self):
        """Link the lead to a customer, creating one from the prospect details when needed."""
        if self.customer_id:
            return self.customer
        from django.core.exceptions import ValidationError

        name = self.company or self.full_name
        if not name:
            raise ValidationError("Enter the company or full name (or pick a customer) before continuing.")
        customer = Customer.objects.filter(name__iexact=name).first()
        if customer is None:
            customer = Customer.create_named(name, **self.customer_details())
        self.customer = customer
        self.save(update_fields=["customer"])
        return customer


class SiteSurvey(Doc):
    SEQ_KEY, SEQ_PREFIX = "SVY", "SV-"
    STATUS = [("draft", "Planned"), ("completed", "Completed")]
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="surveys")
    estimator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    team = models.CharField("Survey team", max_length=200, blank=True)
    visit_date = models.DateField(null=True, blank=True)
    findings = models.TextField(blank=True)
    measurements = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")


COST_CATEGORIES = [("material", "Material"), ("labour", "Labour"), ("subcontract", "Subcontract"),
                   ("other", "Other direct"), ("overhead", "Overhead")]


class Estimation(Doc):
    SEQ_KEY, SEQ_PREFIX = "EST", "ES-"
    STATUS = [("draft", "Draft"), ("approved", "Approved"), ("superseded", "Superseded")]
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="estimations")
    title = models.CharField(max_length=200)
    revision = models.PositiveIntegerField(default=0)
    overhead_percent = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("10"))
    total_cost = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def __str__(self):
        return f"{self.number} · {self.title}"

    def recalc(self):
        self.total_cost = self.lines.aggregate(t=Sum("amount"))["t"] or ZERO
        self.save(update_fields=["total_cost"])

    def cost_by_category(self):
        out = {k: ZERO for k, _ in COST_CATEGORIES}
        for row in self.lines.values("category").annotate(t=Sum("amount")):
            out[row["category"]] = row["t"] or ZERO
        return out


class EstimationLine(models.Model):
    estimation = models.ForeignKey(Estimation, on_delete=models.CASCADE, related_name="lines")
    section = models.CharField(max_length=80, blank=True)
    category = models.CharField(max_length=20, choices=COST_CATEGORIES, default="material")
    product = models.ForeignKey("inventory.Product", null=True, blank=True, on_delete=models.PROTECT)
    description = models.CharField(max_length=250)
    qty = qty_field(default=Decimal("1"))
    uom = models.CharField("UoM", max_length=15, default="nos")
    unit_cost = money_field()
    amount = money_field(editable=False)

    def save(self, *args, **kwargs):
        self.amount = q2(self.qty * self.unit_cost)
        super().save(*args, **kwargs)


class BOQ(Doc):
    SEQ_KEY, SEQ_PREFIX = "BOQ", "BQ-"
    STATUS = [("draft", "Draft"), ("approved", "Approved")]
    estimation = models.ForeignKey(Estimation, on_delete=models.PROTECT, related_name="boqs")
    title = models.CharField(max_length=200)
    overhead_percent = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("10"))
    margin_percent = models.DecimalField("Profit margin %", max_digits=6, decimal_places=2, default=Decimal("15"))
    total_cost = money_field(editable=False)
    total_selling = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    class Meta:
        verbose_name = "BOQ"
        verbose_name_plural = "BOQs"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.number} · {self.title}"

    def apply_margin(self):
        factor = (1 + self.overhead_percent / 100) * (1 + self.margin_percent / 100)
        for line in self.lines.all():
            line.selling_rate = q2(line.unit_cost * factor)
            line.save()
        self.recalc()

    def recalc(self):
        agg = self.lines.aggregate(c=Sum("cost_amount"), s=Sum("selling_amount"))
        self.total_cost = agg["c"] or ZERO
        self.total_selling = agg["s"] or ZERO
        self.save(update_fields=["total_cost", "total_selling"])

    @property
    def gross_margin(self):
        return self.total_selling - self.total_cost


class BOQLine(models.Model):
    boq = models.ForeignKey(BOQ, on_delete=models.CASCADE, related_name="lines")
    section = models.CharField(max_length=80, blank=True)
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


class TermsTemplate(models.Model):
    name = models.CharField(max_length=120)
    is_standard = models.BooleanField(default=False)
    body = models.TextField()

    def __str__(self):
        return self.name


class Quotation(Doc):
    SEQ_KEY, SEQ_PREFIX = "QTN", "QT-"
    APPROVAL_DOC_TYPE = "quotation"
    STATUS = [("draft", "Draft"), ("pm_approval", "Awaiting PM approval"),
              ("sm_approval", "Awaiting SM approval"), ("approved", "Approved"), ("sent", "Sent to client"),
              ("accepted", "Accepted"), ("rejected", "Rejected"), ("revised", "Superseded by revision")]
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="quotations")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    subject = models.CharField(max_length=200)
    boqs = models.ManyToManyField(BOQ, blank=True, verbose_name="BOQs")
    revision = models.PositiveIntegerField(default=0, editable=False)
    terms_template = models.ForeignKey(TermsTemplate, null=True, blank=True, on_delete=models.SET_NULL)
    terms = models.TextField("Terms & conditions", blank=True)
    valid_until = models.DateField(null=True, blank=True)
    currency = models.ForeignKey("core.Currency", null=True, blank=True, on_delete=models.PROTECT)
    discount = money_field()
    subtotal = money_field(editable=False)
    vat_amount = money_field(editable=False)
    total = money_field(editable=False)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    def __str__(self):
        return f"{self.number}" + (f" R{self.revision}" if self.revision else "")

    def approval_amount(self):
        return self.total

    def recalc(self):
        from core.models import Company

        if self.terms_template and not self.terms:
            self.terms = self.terms_template.body
        self.subtotal = (self.lines.aggregate(t=Sum("amount"))["t"] or ZERO) - self.discount
        self.vat_amount = q2(self.subtotal * Company.get().vat_percent / 100)
        self.total = self.subtotal + self.vat_amount
        self.save(update_fields=["terms", "subtotal", "vat_amount", "total"])


class QuotationLine(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")
    section = models.CharField(max_length=80, blank=True)
    description = models.CharField(max_length=250)
    qty = qty_field(default=Decimal("1"))
    uom = models.CharField("UoM", max_length=15, default="nos")
    rate = money_field()
    amount = money_field(editable=False)

    def save(self, *args, **kwargs):
        self.amount = q2(self.qty * self.rate)
        super().save(*args, **kwargs)


class QuotationRevision(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="revisions")
    revision = models.PositiveIntegerField()
    date = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    reason = models.CharField(max_length=300)
    total_before = money_field()
    snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ["-revision"]

    def __str__(self):
        return f"{self.quotation} rev {self.revision}"


class Contract(Doc):
    SEQ_KEY, SEQ_PREFIX = "CON", "CT-"
    STATUS = [("active", "Active"), ("completed", "Completed"), ("cancelled", "Cancelled")]
    quotation = models.OneToOneField(Quotation, on_delete=models.PROTECT, related_name="contract")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    client_po_number = models.CharField("Client PO / contract no.", max_length=60)
    contract_value = money_field(help_text="Excluding VAT")
    advance_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10"))
    retention_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10"))
    payment_terms = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    completion_date = models.DateField(null=True, blank=True)
    client_document = models.FileField(upload_to="contracts/", blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="active")

    def __str__(self):
        return f"{self.number} · {self.client_po_number}"

    @property
    def approved_variations(self):
        from projects.models import VariationOrder

        return VariationOrder.objects.filter(project__contract=self, status="approved").aggregate(
            t=Sum("selling_total"))["t"] or ZERO

    @property
    def revised_value(self):
        return self.contract_value + self.approved_variations
