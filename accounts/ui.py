from core.ui import Action, Inline, Related, Screen, register
from core.workflow import can_approve

from . import workflow as wf
from .models import (Account, AssetCategory, BankAccount, Budget, ControlAccounts, CustomerInvoice, DepreciationLine,
                     DepreciationRun, FixedAsset, JournalEntry, JournalLine, Liability, Receipt, ReceiptAllocation,
                     VendorInvoice, VendorInvoiceLine, VendorPayment, VendorPaymentAllocation)

M = "accounts"
st = lambda *s: (lambda o: o.status in s)  # noqa: E731


class Master(Screen):
    list_filters = ()

    def editable(self, obj):
        return True


@register(M)
class JournalScreen(Screen):
    model = JournalEntry
    slug = "vouchers"
    title = "Vouchers & Journals"
    list_display = ("number", "date", "voucher_type", "narration", "reference", "total", "status")
    search_fields = ("number", "narration", "reference")
    list_filters = ("voucher_type", "status")
    form_fields = ("date", "voucher_type", "reference", "narration", "currency", "exchange_rate")
    detail_fields = ("number", "date", "voucher_type", "reference", "narration", "currency", "exchange_rate", "total",
                     ("Source document", "source_doc"), "reversal_of", "status", "created_by")
    inlines = (Inline(JournalLine, ("account", "description", "debit", "credit", "project", "customer", "vendor", "employee"),
                      extra=4, title="Lines",
                      display=("account", "description", "debit", "credit", "base_debit", "base_credit", "project",
                               "customer", "vendor", "employee"), totals=("debit", "credit", "base_debit", "base_credit")),)
    actions = (
        Action("post", "Post", wf.je_post, st("draft"), style="success"),
        Action("reverse", "Reverse", wf.je_reverse, lambda o: o.status == "posted" and not o.reversal_of_id and not o.reversals.exists(),
               style="danger", groups=["Accounts"], prompt="Reason for reversal"),
    )
    print_template = "print/voucher.html"


@register(M)
class InvoiceScreen(Screen):
    model = CustomerInvoice
    slug = "invoices"
    title = "Progressive Invoicing"
    help_text = "Advance, progressive and final invoices against a contract; advance recovery, retention and VAT are calculated."
    list_display = ("number", "date", "customer", "project", "invoice_type", "gross_amount", "total",
                    ("Balance", "balance"), "status")
    search_fields = ("number", "customer__name", "project__name")
    list_filters = ("status", "invoice_type", "customer")
    form_fields = ("date", "contract", "customer", "project", "invoice_type", "cumulative_percent", "gross_amount",
                   "description", "due_date", "currency", "exchange_rate", "remarks")
    detail_fields = ("number", "date", "customer", "project", "contract", "invoice_type", "cumulative_percent",
                     "description", "gross_amount", "advance_recovery", "retention_amount", "vat_amount", "total",
                     "paid_amount", ("Balance", "balance"), "due_date", ("Retention due", "retention_due_date"),
                     "journal", "status", "remarks")
    actions = (
        Action("post", "Post invoice", wf.invoice_post, st("draft"), style="success"),
        Action("cancel", "Cancel", wf.invoice_cancel, st("posted"), style="danger", groups=["Accounts"],
               prompt="Reason for cancelling"),
    )
    related = (Related("Receipts", lambda o: o.allocations.select_related("receipt"), ("receipt", "amount")),)
    print_template = "print/invoice.html"


@register(M)
class ReceiptScreen(Screen):
    model = Receipt
    slug = "receipts"
    title = "Receipts & PDCs"
    list_display = ("number", "date", "customer", "mode", "cheque_no", "cheque_date", "amount", "status")
    search_fields = ("number", "customer__name", "cheque_no")
    list_filters = ("status", "mode")
    form_fields = ("date", "customer", "project", "mode", "bank_account", "amount", "cheque_no", "cheque_date",
                   "reference", "remarks")
    inlines = (Inline(ReceiptAllocation, ("invoice", "amount"), extra=2, title="Allocate to invoices", totals=("amount",)),)
    actions = (
        Action("post", "Post receipt", wf.receipt_post, st("draft"), style="success"),
        Action("clear", "PDC cleared", wf.receipt_clear, st("pdc"), style="success"),
        Action("bounce", "Bounced", wf.receipt_bounce, st("pdc", "posted"), style="danger",
               prompt="Bank reason for return", confirm="Reverse this receipt as a bounced cheque?"),
    )


@register(M)
class VInvScreen(Screen):
    model = VendorInvoice
    slug = "vendor-invoices"
    title = "Vendor Invoices (3-way match)"
    list_display = ("number", "date", "vendor", "vendor_invoice_no", "purchase_order", "total", ("Balance", "balance"), "status")
    search_fields = ("number", "vendor__name", "vendor_invoice_no")
    list_filters = ("status", "vendor")
    form_fields = ("date", "vendor", "purchase_order", "vendor_invoice_no", "project", "due_date", "currency",
                   "exchange_rate", "vat_amount", "remarks")
    detail_fields = ("number", "date", "vendor", "vendor_invoice_no", "purchase_order", "project", "due_date",
                     "currency", "exchange_rate", "subtotal", "vat_amount", "total", "paid_amount", ("Balance", "balance"),
                     "match_notes", "discrepancy_approved", "journal", "status", "remarks")
    inlines = (Inline(VendorInvoiceLine, ("po_line", "account", "description", "qty", "rate"), extra=1,
                      display=("po_line", "account", "description", "qty", "rate", "amount", "match_result"),
                      totals=("amount",)),)
    actions = (
        Action("match", "Run 3-way match", wf.vinv_match, st("draft", "discrepancy", "matched")),
        Action("accept", "Accept discrepancy", wf.vinv_accept_discrepancy, st("discrepancy"), style="warn",
               groups=["Senior Manager"], prompt="Justification"),
        Action("post", "Post to AP", wf.vinv_post, st("matched"), style="success"),
    )

    def editable(self, obj):
        return obj.status in ("draft", "discrepancy", "matched")


@register(M)
class VPayScreen(Screen):
    model = VendorPayment
    slug = "vendor-payments"
    title = "Vendor Payments & Cheques"
    list_display = ("number", "date", "vendor", "mode", "cheque_no", "cheque_date", "amount", "status")
    search_fields = ("number", "vendor__name", "cheque_no")
    list_filters = ("status", "mode")
    form_fields = ("date", "vendor", "bank_account", "mode", "amount", "cheque_no", "cheque_date", "payee_name", "remarks")
    inlines = (Inline(VendorPaymentAllocation, ("invoice", "amount"), extra=2, title="Invoices paid", totals=("amount",)),)
    actions = (
        Action("submit", "Submit for approval", wf.vpay_submit, st("draft")),
        Action("approve", "Approve", wf.vpay_approve, st("pending_approval"), style="success", check=can_approve,
               prompt="Comment (optional)"),
        Action("post", "Pay / post", wf.vpay_post, st("approved"), style="success"),
        Action("clear", "PDC presented", wf.vpay_clear, st("posted"), style="ghost") ,
    )
    print_template = "print/cheque.html"


@register(M)
class BankScreen(Master):
    model = BankAccount
    slug = "banks"
    title = "Bank Accounts"
    list_display = ("name", "bank_name", "account", "iban", "currency", "next_cheque_no")


@register(M)
class AccountScreen(Master):
    model = Account
    slug = "chart"
    title = "Chart of Accounts"
    list_display = ("code", "name", "type", "parent", "is_group", "cost_category", ("Balance", "balance"))
    search_fields = ("code", "name")
    list_filters = ("type", "is_group", "cost_category")
    ordering = ("code",)
    related = (Related("Recent postings", lambda o: o.lines.filter(entry__status="posted").select_related("entry")
                       .order_by("-entry__date")[:30],
                       ("entry", "entry__date", "description", "base_debit", "base_credit", "project")),)


@register(M)
class ControlScreen(Master):
    model = ControlAccounts
    slug = "control-accounts"
    title = "Control Accounts"
    list_display = (("Mapping", str), "receivable", "payable", "grni", "inventory")
    can_create = False

    def deletable(self, obj):
        return False


@register(M)
class AssetScreen(Master):
    model = FixedAsset
    slug = "assets"
    title = "Fixed Asset Register"
    list_display = ("code", "name", "category", "purchase_date", "cost", ("Accumulated dep.", "accumulated_depreciation"),
                    ("Net book value", "net_book_value"), "status")
    search_fields = ("code", "name", "registration_no")
    list_filters = ("category", "status")
    related = (Related("Depreciation", lambda o: o.depreciation_lines.select_related("run"), ("run", "run__period_end", "amount")),)


@register(M)
class AssetCatScreen(Master):
    model = AssetCategory
    slug = "asset-categories"
    title = "Asset Categories"
    list_display = ("name", "asset_account", "useful_life_months")


@register(M)
class DepScreen(Screen):
    model = DepreciationRun
    slug = "depreciation"
    title = "Depreciation Runs"
    list_display = ("number", "period_end", "total", "status")
    form_fields = ("date", "period_end", "remarks")
    inlines = (Inline(DepreciationLine, ("asset", "amount"), extra=0, readonly=True, totals=("amount",)),)
    actions = (
        Action("compute", "Compute", wf.dep_compute, st("draft")),
        Action("post", "Post", wf.dep_post, st("draft"), style="success"),
    )


@register(M)
class BudgetScreen(Master):
    model = Budget
    slug = "budgets"
    list_display = ("fiscal_year", "account", "project", ("Annual", "annual"))
    list_filters = ("fiscal_year",)
    search_fields = ("account__name", "account__code")


@register(M)
class LiabilityScreen(Master):
    model = Liability
    slug = "liabilities"
    list_display = ("name", "liability_type", "lender", "principal", "interest_rate", "monthly_installment",
                    ("Outstanding (GL)", "outstanding"))
