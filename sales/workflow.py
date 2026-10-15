from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import Max

from core.services import require_status
from core.workflow import approve_step, open_edit, set_status, submit_for_approval

from .models import BOQ, BOQLine, Contract, Estimation, EstimationLine, QuotationLine, QuotationRevision, SiteSurvey


# --- leads -------------------------------------------------------------------

def lead_review(request, lead):
    set_status(lead, "under_review")


def lead_qualify(request, lead):
    if not lead.capability_review:
        raise ValidationError("Record the capability review (scope vs capability) before qualifying the lead.")
    lead.ensure_customer()
    set_status(lead, "qualified")
    return "Lead qualified and ready for estimation."


def lead_reject(request, lead):
    lead.capability_review = (lead.capability_review + f"\nRejected: {request.action_comment}").strip()
    lead.status = "rejected"
    lead.save()


def lead_lost(request, lead):
    set_status(lead, "lost")


def lead_survey(request, lead):
    survey = SiteSurvey.objects.create(lead=lead, estimator=request.user, visit_date=lead.date)
    return open_edit(request, survey, "Site survey created. Fill in the team, findings and visits.")


def lead_estimation(request, lead):
    require_status(lead, "qualified", "estimation", "quoted")
    est = Estimation.objects.create(lead=lead, title=lead.title)
    if lead.status == "qualified":
        set_status(lead, "estimation")
    return open_edit(request, est, "Estimation created. Add material, labour, subcontract and overhead lines.")


def survey_complete(request, survey):
    set_status(survey, "completed")


# --- estimation --------------------------------------------------------------

def estimation_approve(request, est):
    if not est.lines.exists():
        raise ValidationError("Add estimation lines first.")
    set_status(est, "approved")


def estimation_revise(request, est):
    new = Estimation.objects.create(lead=est.lead, title=est.title, overhead_percent=est.overhead_percent,
                                    revision=est.revision + 1, remarks=f"Revision of {est.number}: {request.action_comment}")
    for l in est.lines.all():
        l.pk = None
        l.estimation = new
        l.save()
    new.recalc()
    set_status(est, "superseded")
    return open_edit(request, new)


def estimation_boq(request, est):
    require_status(est, "approved")
    boq = BOQ.objects.create(estimation=est, title=est.title, overhead_percent=est.overhead_percent)
    for l in est.lines.exclude(category="overhead"):
        BOQLine.objects.create(boq=boq, section=l.section, category=l.category, description=l.description,
                               qty=l.qty, uom=l.uom, unit_cost=l.unit_cost)
    boq.apply_margin()
    return open_edit(request, boq, "BOQ created from the estimation; set overhead and margin, then apply margin.")


def estimation_to_store(request, est):
    """Share the estimation sheet with the store, without prices, for material planning."""
    from inventory.models import MaterialRequisition, MaterialRequisitionLine, Warehouse

    project = None
    quotation = est.lead.quotations.filter(status="accepted").first()
    if quotation and hasattr(quotation, "contract"):
        project = quotation.contract.projects.first()
    wh = Warehouse.objects.order_by("id").first()
    if wh is None:
        raise ValidationError("Create a warehouse first.")
    mr = MaterialRequisition.objects.create(estimation=est, is_planning_sheet=True, warehouse=wh, project=project,
                                            requested_by=str(request.user),
                                            remarks=f"Estimation sheet {est.number} shared for material planning (no prices).")
    skipped = 0
    for l in est.lines.filter(category="material"):
        if l.product_id:
            MaterialRequisitionLine.objects.create(requisition=mr, product=l.product, qty=l.qty, note=l.description[:200])
        else:
            skipped += 1
    if skipped:
        mr.remarks += f" {skipped} material line(s) without a product code were not transferred."
        mr.save(update_fields=["remarks"])
    return mr


# --- BOQ ---------------------------------------------------------------------

def boq_apply_margin(request, boq):
    boq.apply_margin()
    return f"Selling rates updated: cost {boq.total_cost:,.2f} → selling {boq.total_selling:,.2f}."


def boq_approve(request, boq):
    if not boq.lines.exists():
        raise ValidationError("BOQ has no lines.")
    set_status(boq, "approved")


def boq_quotation(request, boq):
    from core.models import Company
    from .models import Quotation, TermsTemplate

    require_status(boq, "approved")
    lead = boq.estimation.lead
    terms = TermsTemplate.objects.filter(is_standard=True).first()
    q = Quotation.objects.create(lead=lead, customer=lead.ensure_customer(), subject=lead.title, terms_template=terms,
                                 terms=terms.body if terms else "", valid_until=boq.date + timedelta(days=30))
    q.boqs.add(boq)
    rebuild_lines(q)
    return open_edit(request, q, "Quotation drafted from the BOQ. Add more BOQs if needed and use 'Rebuild lines'.")


# --- quotation ---------------------------------------------------------------

def rebuild_lines(q):
    q.lines.all().delete()
    for boq in q.boqs.all():
        for l in boq.lines.all():
            QuotationLine.objects.create(quotation=q, section=l.section or boq.title[:80], description=l.description,
                                         qty=l.qty, uom=l.uom, rate=l.selling_rate)
    q.recalc()


def quotation_rebuild(request, q):
    rebuild_lines(q)
    return "Lines rebuilt from the selected BOQs."


def _quote_status_for(rule):
    return "sm_approval" if rule and rule.level >= 2 else "pm_approval"


def quotation_submit(request, q):
    if not q.lines.exists():
        raise ValidationError("Quotation has no lines.")
    rule = submit_for_approval(q, pending_status="pm_approval")
    if rule:
        set_status(q, _quote_status_for(rule))


def quotation_approve(request, q):
    approve_step(request, q, approved_status="approved", rejected_status="draft", status_for_rule=_quote_status_for)


def quotation_send(request, q):
    set_status(q, "sent")
    if q.lead.status in ("qualified", "estimation", "under_review"):
        set_status(q.lead, "quoted")


def quotation_revise(request, q):
    if not request.action_comment:
        raise ValidationError("A reason is required for a revision.")
    snapshot = {
        "subtotal": str(q.subtotal), "total": str(q.total), "terms": q.terms,
        "lines": [{"section": l.section, "description": l.description, "qty": str(l.qty), "uom": l.uom,
                   "rate": str(l.rate)} for l in q.lines.all()],
    }
    next_rev = (q.revisions.aggregate(m=Max("revision"))["m"] or 0) + 1
    QuotationRevision.objects.create(quotation=q, revision=next_rev, user=request.user, reason=request.action_comment,
                                     total_before=q.total, snapshot=snapshot)
    q.revision = next_rev
    q.status = "draft"
    q.save(update_fields=["revision", "status"])
    from core.services import reset_approvals

    reset_approvals(q)
    return open_edit(request, q, f"Revision {next_rev} opened.")


def quotation_accept(request, q):
    set_status(q, "accepted")
    set_status(q.lead, "won")


def quotation_client_reject(request, q):
    set_status(q, "rejected")
    set_status(q.lead, "lost")


def quotation_contract(request, q):
    require_status(q, "accepted")
    if Contract.objects.filter(quotation=q).exists():
        return q.contract
    c = Contract.objects.create(quotation=q, customer=q.customer, client_po_number=request.action_comment or "TBC",
                                contract_value=q.subtotal, start_date=q.date)
    return open_edit(request, c, "Contract created. Attach the client PO / contract document.")


# --- contract ----------------------------------------------------------------

def contract_project(request, contract):
    from projects.models import Project

    existing = contract.projects.first()
    if existing:
        return existing
    year = contract.date.year
    n = Project.objects.filter(code__startswith=f"P{year}-").count() + 1
    budget = {"material": 0, "labour": 0, "subcontract": 0, "overhead": 0}
    for boq in contract.quotation.boqs.all():
        for l in boq.lines.all():
            key = l.category if l.category in budget else "overhead"
            budget[key] += l.cost_amount
        budget["overhead"] += boq.total_cost * boq.overhead_percent / 100
    project = Project.objects.create(
        code=f"P{year}-{n:03d}", name=contract.quotation.subject, customer=contract.customer,
        quotation=contract.quotation, contract=contract, manager=request.user, start_date=contract.start_date,
        end_date=contract.completion_date, contract_value=contract.contract_value, location=contract.quotation.lead.location,
        budget_material=round(budget["material"], 2), budget_labour=round(budget["labour"], 2),
        budget_subcontract=round(budget["subcontract"], 2), budget_overhead=round(budget["overhead"], 2),
    )
    # link estimation sheets already shared with the store
    from inventory.models import MaterialRequisition

    MaterialRequisition.objects.filter(estimation__boqs__in=contract.quotation.boqs.all(), project__isnull=True) \
        .update(project=project)
    return project
