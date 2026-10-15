from core.ui import Action, Inline, Related, Screen, register
from core.workflow import can_approve

from . import workflow as wf
from .forms import use_customer_box
from .models import (BOQ, BOQLine, Contract, Customer, Estimation, EstimationLine, Lead, Quotation, QuotationLine,
                     SiteSurvey, TermsTemplate)

M = "sales"
st = lambda *s: (lambda o: o.status in s)  # noqa: E731


@register(M)
class LeadScreen(Screen):
    model = Lead
    slug = "leads"
    list_display = ("number", "date", ("Contact", "contact_name"), "company", "mobile", "title", "source",
                    "expected_value", "status")
    search_fields = ("number", "title", "full_name", "company", "email", "mobile", "customer__name", "location")
    list_filters = ("status", "source")
    form_fields = ("date", "salutation", "full_name", "company", "email", "mobile", "website", "source", "status",
                   "title", "customer", "location", "expected_value", "salesperson", "scope", "capability_review",
                   "remarks")
    detail_fields = ("number", "date", "salutation", "full_name", "company", "email", "mobile", "website", "source",
                     "status", "title", "customer", "location", "expected_value", "salesperson", "scope",
                     "capability_review", "remarks")
    actions = (
        Action("review", "Start scope review", wf.lead_review, st("new")),
        Action("qualify", "Qualify", wf.lead_qualify, st("new", "under_review"), style="success"),
        Action("reject", "Reject", wf.lead_reject, st("new", "under_review"), style="danger", prompt="Reason for rejecting"),
        Action("survey", "+ Site survey", wf.lead_survey, st("under_review", "qualified", "estimation")),
        Action("estimate", "+ Estimation", wf.lead_estimation, st("qualified", "estimation", "quoted")),
        Action("lost", "Mark lost", wf.lead_lost, st("quoted", "estimation"), style="danger", confirm="Mark this lead as lost?"),
    )
    related = (
        Related("Site surveys", lambda o: o.surveys.all(), ("number", "visit_date", "estimator", "status")),
        Related("Estimations", lambda o: o.estimations.all(), ("number", "title", "revision", "total_cost", "status")),
        Related("Quotations", lambda o: o.quotations.all(), ("number", "revision", "subject", "total", "status")),
    )

    def editable(self, obj):
        return obj.status in ("new", "under_review", "qualified", "estimation")

    def setup_form(self, form, request, obj):
        for name in ("full_name", "mobile"):
            if name in form.fields:
                form.fields[name].required = True
        use_customer_box(form, lambda lead: lead.customer_details())


@register(M)
class SurveyScreen(Screen):
    model = SiteSurvey
    slug = "surveys"
    title = "Site Surveys"
    list_display = ("number", "visit_date", "lead", "estimator", "team", "status")
    search_fields = ("number", "lead__title", "findings")
    form_fields = ("lead", "estimator", "team", "visit_date", "findings", "measurements", "remarks")
    actions = (Action("complete", "Mark completed", wf.survey_complete, st("draft"), style="success"),)


@register(M)
class EstimationScreen(Screen):
    model = Estimation
    slug = "estimations"
    list_display = ("number", "date", "title", "lead", "revision", "total_cost", "status")
    search_fields = ("number", "title", "lead__title")
    form_fields = ("date", "lead", "title", "overhead_percent", "remarks")
    inlines = (Inline(EstimationLine, ("section", "category", "product", "description", "qty", "uom", "unit_cost"),
                      extra=5, title="Cost lines (material, labour, subcontract, other direct, overhead)",
                      display=("section", "category", "product", "description", "qty", "uom", "unit_cost", "amount"),
                      totals=("amount",)),)
    actions = (
        Action("approve", "Approve", wf.estimation_approve, st("draft"), style="success"),
        Action("boq", "+ Create BOQ", wf.estimation_boq, st("approved")),
        Action("store", "Send sheet to store", wf.estimation_to_store, st("approved"),
               confirm="Share this estimation (quantities only, no prices) with the store for material planning?"),
        Action("revise", "New revision", wf.estimation_revise, st("draft", "approved"), style="ghost",
               prompt="Reason for revision"),
    )
    related = (
        Related("BOQs", lambda o: o.boqs.all(), ("number", "title", "total_cost", "total_selling", "status")),
        Related("Estimation sheets sent to store", lambda o: o.materialrequisition_set.all(),
                ("number", "date", "warehouse", "project", "status")),
    )


@register(M)
class BOQScreen(Screen):
    model = BOQ
    slug = "boqs"
    title = "BOQs"
    list_display = ("number", "date", "title", "estimation", "total_cost", "total_selling", "status")
    search_fields = ("number", "title")
    form_fields = ("date", "estimation", "title", "overhead_percent", "margin_percent", "remarks")
    detail_fields = ("number", "date", "title", "estimation", "overhead_percent", "margin_percent", "total_cost",
                     "total_selling", ("Gross margin", "gross_margin"), "status", "remarks")
    inlines = (Inline(BOQLine, ("section", "category", "description", "qty", "uom", "unit_cost", "selling_rate"),
                      extra=3, display=("section", "category", "description", "qty", "uom", "unit_cost",
                                        "cost_amount", "selling_rate", "selling_amount"),
                      totals=("cost_amount", "selling_amount")),)
    actions = (
        Action("margin", "Apply overhead & margin", wf.boq_apply_margin, st("draft")),
        Action("approve", "Approve BOQ", wf.boq_approve, st("draft"), style="success"),
        Action("quote", "+ Create quotation", wf.boq_quotation, st("approved")),
    )


@register(M)
class TermsScreen(Screen):
    model = TermsTemplate
    slug = "terms"
    title = "T&C Templates"
    list_display = ("name", "is_standard")
    search_fields = ("name",)
    list_filters = ()


@register(M)
class QuotationScreen(Screen):
    model = Quotation
    slug = "quotations"
    list_display = ("number", "revision", "date", "customer", "subject", "total", "status")
    search_fields = ("number", "subject", "customer__name")
    list_filters = ("status",)
    form_fields = ("date", "lead", "customer", "subject", "boqs", "valid_until", "currency", "discount",
                   "terms_template", "terms", "remarks")
    detail_fields = ("number", "revision", "date", "lead", "customer", "subject", "boqs", "valid_until", "currency",
                     "subtotal", "discount", "vat_amount", "total", "status", "terms", "remarks")
    inlines = (Inline(QuotationLine, ("section", "description", "qty", "uom", "rate"), extra=2,
                      display=("section", "description", "qty", "uom", "rate", "amount"), totals=("amount",)),)
    actions = (
        Action("rebuild", "Rebuild lines from BOQs", wf.quotation_rebuild, st("draft"), style="ghost",
               confirm="Replace the lines with the selling lines of the selected BOQs?"),
        Action("submit", "Submit for approval", wf.quotation_submit, st("draft")),
        Action("approve", "Approve", wf.quotation_approve, st("pm_approval", "sm_approval"), style="success",
               check=can_approve, prompt="Approval comment (optional)"),
        Action("send", "Mark sent to client", wf.quotation_send, st("approved")),
        Action("accept", "Client accepted", wf.quotation_accept, st("sent"), style="success"),
        Action("client_reject", "Client rejected", wf.quotation_client_reject, st("sent"), style="danger"),
        Action("revise", "Revise", wf.quotation_revise, st("draft", "approved", "sent", "pm_approval", "sm_approval"),
               style="ghost", prompt="Reason for revision"),
        Action("contract", "Convert to contract", wf.quotation_contract,
               lambda o: o.status == "accepted" and not hasattr(o, "contract"),
               prompt="Client PO / contract number"),
    )
    related = (
        Related("Revision history", lambda o: o.revisions.all(), ("revision", "date", "user", "reason", "total_before")),
    )
    print_template = "print/quotation.html"

    def setup_form(self, form, request, obj):
        if "boqs" in form.fields:
            form.fields["boqs"].queryset = BOQ.objects.filter(status="approved")


@register(M)
class ContractScreen(Screen):
    model = Contract
    slug = "contracts"
    title = "Client PO / Contracts"
    list_display = ("number", "date", "client_po_number", "customer", "contract_value", ("Revised value", "revised_value"), "status")
    search_fields = ("number", "client_po_number", "customer__name")
    form_fields = ("date", "quotation", "customer", "client_po_number", "contract_value", "advance_percent",
                   "retention_percent", "start_date", "completion_date", "payment_terms", "client_document", "remarks")
    detail_fields = ("number", "date", "quotation", "customer", "client_po_number", "contract_value",
                     ("Approved variations", "approved_variations"), ("Revised value", "revised_value"),
                     "advance_percent", "retention_percent", "start_date", "completion_date", "client_document",
                     "status", "payment_terms", "remarks")
    actions = (
        Action("project", "+ Create project", wf.contract_project, lambda o: not o.projects.exists()),
    )
    related = (
        Related("Projects", lambda o: o.projects.all(), ("code", "name", "manager", "status")),
        Related("Invoices", lambda o: o.invoices.all(), ("number", "date", "invoice_type", "gross_amount", "total", "status")),
    )

    def editable(self, obj):
        return obj.status == "active"


@register(M)
class CustomerScreen(Screen):
    model = Customer
    slug = "customers"
    list_display = ("code", "name", "contact_person", "phone", "credit_days", "active")
    search_fields = ("code", "name", "contact_person")
    list_filters = ("active",)
    related = (
        Related("Leads", lambda o: o.lead_set.all()[:20], ("number", "title", "status")),
        Related("Projects", lambda o: o.project_set.all(), ("code", "name", "status")),
    )

    def editable(self, obj):
        return True
