from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

ZERO = Decimal("0")


def money_field(verbose_name=None, **kw):
    if verbose_name:
        kw["verbose_name"] = verbose_name
    kw.setdefault("max_digits", 16)
    kw.setdefault("decimal_places", 2)
    kw.setdefault("default", ZERO)
    return models.DecimalField(**kw)


def qty_field(verbose_name=None, **kw):
    if verbose_name:
        kw["verbose_name"] = verbose_name
    kw.setdefault("max_digits", 14)
    kw.setdefault("decimal_places", 3)
    kw.setdefault("default", ZERO)
    return models.DecimalField(**kw)


def today():
    return timezone.localdate()


class Company(models.Model):
    name = models.CharField(max_length=200, default="Fit-Out Company LLC")
    trn = models.CharField("TRN", max_length=30, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    base_currency = models.CharField(max_length=3, default="AED")
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5"))
    normal_ot_rate = models.DecimalField("Normal OT multiplier", max_digits=4, decimal_places=2, default=Decimal("1.25"))
    friday_ot_rate = models.DecimalField("Friday OT multiplier", max_digits=4, decimal_places=2, default=Decimal("1.50"))
    holiday_ot_rate = models.DecimalField("Public holiday OT multiplier", max_digits=4, decimal_places=2, default=Decimal("1.50"))
    retention_due_days = models.PositiveIntegerField(default=400)
    employer_eid = models.CharField("WPS employer ID (MOL establishment)", max_length=30, blank=True)
    employer_bank_routing = models.CharField("WPS bank routing code", max_length=20, blank=True)

    class Meta:
        verbose_name_plural = "company"

    def __str__(self):
        return self.name

    @classmethod
    def get(cls):
        obj = cls.objects.first()
        return obj or cls.objects.create()


class Currency(models.Model):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=50)
    rate = models.DecimalField("Rate to base", max_digits=12, decimal_places=6, default=Decimal("1"))

    class Meta:
        verbose_name_plural = "currencies"
        ordering = ["code"]

    def __str__(self):
        return self.code


class Sequence(models.Model):
    key = models.CharField(max_length=30, unique=True)
    prefix = models.CharField(max_length=20)
    next_value = models.PositiveIntegerField(default=1)
    padding = models.PositiveSmallIntegerField(default=5)

    def __str__(self):
        return f"{self.prefix} ({self.next_value})"


class Attachment(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    obj = GenericForeignKey("content_type", "object_id")
    file = models.FileField(upload_to="attachments/%Y/%m/")
    description = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.description or self.file.name


class AuditLog(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    obj = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField(max_length=200)
    action = models.CharField(max_length=60)
    changes = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.user} {self.action} {self.object_repr}"


class ApprovalRule(models.Model):
    DOC_TYPES = [
        ("quotation", "Quotation"),
        ("purchase_requisition", "Purchase requisition"),
        ("purchase_order", "Purchase order"),
        ("variation_order", "Variation order"),
        ("stock_adjustment", "Stock adjustment"),
        ("vendor_payment", "Vendor payment"),
        ("leave", "Leave application"),
    ]
    doc_type = models.CharField(max_length=40, choices=DOC_TYPES)
    level = models.PositiveSmallIntegerField(default=1)
    group = models.ForeignKey(Group, on_delete=models.PROTECT, help_text="Role that approves this level")
    min_amount = money_field()
    max_amount = money_field(null=True, blank=True, default=None, help_text="Blank = no upper limit")

    class Meta:
        ordering = ["doc_type", "level", "min_amount"]

    def __str__(self):
        upper = f"{self.max_amount:,.0f}" if self.max_amount is not None else "∞"
        return f"{self.get_doc_type_display()} L{self.level}: {self.group} ({self.min_amount:,.0f}–{upper})"


class ApprovalLog(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    obj = GenericForeignKey("content_type", "object_id")
    level = models.PositiveSmallIntegerField()
    group_name = models.CharField(max_length=80)
    decision = models.CharField(max_length=10, choices=[("approved", "Approved"), ("rejected", "Rejected")])
    comment = models.CharField(max_length=300, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]


class Doc(models.Model):
    """Base for numbered business documents."""

    SEQ_KEY = "DOC"
    SEQ_PREFIX = "DOC-"

    number = models.CharField(max_length=30, blank=True, editable=False, db_index=True)
    date = models.DateField(default=today)
    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-id"]

    def save(self, *args, **kwargs):
        if not self.number:
            from core.services import next_number

            self.number = next_number(self.SEQ_KEY, self.SEQ_PREFIX)
        if not self.created_by_id:
            from core.middleware import get_current_user

            user = get_current_user()
            if user is not None and user.is_authenticated:
                self.created_by = user
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number or f"{self._meta.verbose_name} (new)"
