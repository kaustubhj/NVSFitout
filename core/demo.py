"""End-to-end demo scenario. It drives every module through the same workflow functions the UI
buttons call, so it doubles as an integration test of the cross-module flows."""
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.utils import timezone


class _Messages(list):
    def add(self, level, message, extra_tags=""):
        self.append(message)


class Req:
    def __init__(self, username, comment="", decision=None):
        self.user = User.objects.get(username=username)
        self.action_comment = comment
        self.POST = {"decision": decision} if decision else {}
        self._messages = _Messages()


def act(username, func, obj, comment="", decision=None):
    result = func(Req(username, comment, decision), obj)
    obj.refresh_from_db()
    return result


def run_demo(stdout=None):
    say = (lambda m: stdout.write(m)) if stdout else (lambda m: None)
    from accounts import workflow as awf
    from accounts.models import (BankAccount, BankStatementLine, Budget, CustomerInvoice, DepreciationRun, FixedAsset,
                                 AssetCategory, Account, Receipt, ReceiptAllocation, VendorInvoice, VendorPayment,
                                 VendorPaymentAllocation)
    from accounts.reports import auto_match
    from hrms import ui as hui
    from hrms.models import (Attendance, AttendanceSheet, Deduction, Designation, Department, Employee, EmployeeDocument,
                             LeaveApplication, LeaveType, Loan, Mobilization, MobilizationLine, PayrollRun, Room,
                             RoomAllocation, Trade, VisaQuota)
    from inventory import workflow as iwf
    from inventory.models import (GoodsReceipt, MaterialRequisition, MaterialRequisitionLine, Product, ProjectReturn,
                                  ProjectReturnLine, StockAdjustment, StockAdjustmentLine, StockTransfer,
                                  StockTransferLine, Warehouse)
    from procurement import workflow as pwf
    from procurement.models import LandedCost, LandedCostCharge, PurchaseOrder, PurchaseRequisition, Vendor
    from projects import ui as pui
    from projects.models import Project, VariationLine, VariationOrder
    from sales import workflow as swf
    from sales.models import (BOQ, Contract, Customer, Estimation, EstimationLine, Lead, Quotation, TermsTemplate)

    if Lead.objects.exists():
        say("Demo data already present; skipped.")
        return
    today = timezone.localdate()
    start = today - timedelta(days=75)
    P = {p.code: p for p in Product.objects.all()}
    main = Warehouse.objects.get(code="MAIN")
    site = Warehouse.objects.get(code="SITE")
    pm = User.objects.get(username="pm")

    # --- customers & vendors ------------------------------------------------------
    cust = Customer.objects.create(code="C001", name="Al Noor Real Estate LLC", trn="100555666700003",
                                   contact_person="Mr. Hamad", phone="+971 50 111 2233", credit_days=45,
                                   address="Sheikh Zayed Road, Dubai")
    cust2 = Customer.objects.create(code="C002", name="Bayview Hospitality", credit_days=30, contact_person="Ms. Leena")
    Customer.objects.create(code="C003", name="Gulf Medical Clinics", credit_days=60)
    vendors = [
        Vendor.objects.create(code="V001", name="Emirates Gypsum Trading", category="Drywall", payment_terms="30 days",
                              trn="100777888900003"),
        Vendor.objects.create(code="V002", name="Al Ain Building Materials", category="General", payment_terms="45 days"),
        Vendor.objects.create(code="V003", name="Prime Interiors Supply", category="Drywall / Flooring", payment_terms="60 days"),
        Vendor.objects.create(code="V004", name="Coolbreeze MEP Contracting", category="MEP", is_subcontractor=True),
        Vendor.objects.create(code="V005", name="Speedline Freight & Clearing", category="Logistics"),
    ]

    # --- opening stock ----------------------------------------------------------------
    adj = StockAdjustment.objects.create(warehouse=main, reason="opening", date=start, remarks="Opening stock")
    for code, qty in [("GYP-12", 120), ("STD-70", 300), ("TRK-70", 150), ("PNT-EM", 25), ("PNT-PR", 12),
                      ("TIL-60", 40), ("ADH-25", 60), ("MDF-18", 35), ("HNG-01", 400), ("SCR-25", 50), ("CT-600", 80)]:
        StockAdjustmentLine.objects.create(adjustment=adj, product=P[code], qty_change=qty, unit_cost=P[code].standard_cost)
    act("store", iwf.adjustment_submit, adj)
    act("sm", iwf.adjustment_approve, adj)
    say(f"Opening stock posted: {adj.number} ({adj.total_value:,.2f})")

    # --- sales: lead → contract --------------------------------------------------------
    lead = Lead.objects.create(date=start, title="Office fit-out, Level 12, Al Noor Tower", customer=cust,
                               salutation="Mr.", full_name="Khalid Al Mansoori", company="Al Noor Real Estate LLC",
                               email="khalid@alnoor.example", mobile="+971 50 123 4567", website="https://alnoor.example",
                               source="consultant", location="Business Bay, Dubai", expected_value=D("850000"),
                               scope="Partitions, ceilings, flooring, joinery, painting and MEP modifications, 1,200 sqm.",
                               salesperson=User.objects.get(username="sales"))
    act("sales", swf.lead_review, lead)
    lead.capability_review = "Within capability: all trades in-house except MEP (subcontract)."
    lead.save()
    act("sales", swf.lead_qualify, lead)
    act("estimator", swf.lead_survey, lead)
    survey = lead.surveys.get()
    survey.team = "Omar (estimator), Priya (PM)"
    survey.findings = "Shell & core handed over. Raised floor exists. Ceiling height 3.2 m."
    survey.save()
    act("estimator", swf.survey_complete, survey)
    act("estimator", swf.lead_estimation, lead)
    est = lead.estimations.get()
    for section, cat, prod, desc, qty, uom, cost in [
        ("Partitions", "material", "GYP-12", "Gypsum board partitions", 400, "sht", "28"),
        ("Partitions", "material", "STD-70", "Metal studs", 900, "pcs", "9.5"),
        ("Partitions", "material", "TRK-70", "Metal track", 300, "pcs", "8"),
        ("Ceilings", "material", "CT-600", "Mineral fibre ceiling", 600, "pcs", "12"),
        ("Flooring", "material", "TIL-60", "Porcelain tiles", 450, "sqm", "65"),
        ("Flooring", "material", "CPT-01", "Carpet tiles", 500, "sqm", "85"),
        ("Flooring", "material", "ADH-25", "Tile adhesive", 90, "bag", "22"),
        ("Joinery", "material", "MDF-18", "Joinery MDF", 60, "sht", "95"),
        ("Painting", "material", "PNT-EM", "Emulsion paint", 40, "pail", "145"),
        ("MEP", "subcontract", None, "MEP modifications (subcontract)", 1, "ls", "120000"),
        ("General", "other", None, "Site preliminaries, scaffolding, cleaning", 1, "ls", "18000"),
    ]:
        EstimationLine.objects.create(estimation=est, section=section, category=cat, product=P.get(prod),
                                      description=desc, qty=qty, uom=uom, unit_cost=D(cost))
    for desig, persons, days, rate in [("Skilled Labour", 10, 35, "150"), ("Helper", 5, 35, "84")]:
        EstimationLine.objects.create(estimation=est, section="Labour", category="labour",
                                      designation=Designation.objects.get(name=desig), persons=persons, days=days,
                                      unit_cost=D(rate))
    est.recalc()
    act("estimator", swf.estimation_approve, est)
    act("estimator", swf.estimation_to_store, est)
    act("estimator", swf.estimation_boq, est)
    boq = est.boqs.get()
    boq.margin_percent = D("18")
    boq.save()
    act("estimator", swf.boq_apply_margin, boq)
    act("estimator", swf.boq_approve, boq)
    act("sales", swf.boq_quotation, boq)
    q = Quotation.objects.get(lead=lead)
    act("sales", swf.quotation_submit, q)
    act("pm", swf.quotation_approve, q)
    act("sm", swf.quotation_approve, q)
    act("sales", swf.quotation_send, q)
    q.discount = D("15000")
    q.save()
    act("sales", swf.quotation_revise, q, "Client asked for a 15,000 commercial discount")
    q.recalc()
    act("sales", swf.quotation_submit, q)
    act("pm", swf.quotation_approve, q)
    act("sm", swf.quotation_approve, q)
    act("sales", swf.quotation_send, q)
    act("sales", swf.quotation_accept, q)
    act("sales", swf.quotation_contract, q, "ANRE/PO/2026/0412")
    contract = Contract.objects.get(quotation=q)
    contract.date = start + timedelta(days=10)
    contract.start_date = contract.date
    contract.completion_date = contract.date + timedelta(days=120)
    contract.save()
    act("pm", swf.contract_project, contract)
    project = contract.projects.get()
    project.start_date = contract.date
    project.save()
    say(f"Sales: {lead.number} → {est.number} → {boq.number} → {q} (rev {q.revision}) → {contract.number} → {project.code}")

    # second lead in the pipeline
    lead2 = Lead.objects.create(title="Hotel lobby refurbishment", customer=cust2, source="tender",
                                salutation="Ms.", full_name="Leena Sharma", company="Bayview Hospitality",
                                email="leena@bayview.example", mobile="+971 55 765 4321",
                                location="Palm Jumeirah", expected_value=D("1200000"))
    act("sales", swf.lead_review, lead2)

    # --- material requisition → stock check → PR → RFQ → PO → GRN ---------------------
    mr = MaterialRequisition.objects.create(project=project, warehouse=main, date=start + timedelta(days=14),
                                            required_date=start + timedelta(days=21), requested_by="Site engineer")
    for code, qty in [("GYP-12", 400), ("STD-70", 900), ("TRK-70", 300), ("SCR-25", 20), ("PNT-PR", 8)]:
        MaterialRequisitionLine.objects.create(requisition=mr, product=P[code], qty=qty)
    act("pm", iwf.mr_submit, mr)
    act("store", iwf.mr_stock_check, mr)
    pr = PurchaseRequisition.objects.get(material_requisition=mr)
    act("procurement", pwf.pr_submit, pr)
    act("pm", pwf.pr_approve, pr)
    act("procurement", pwf.pr_rfq, pr)
    rfq = pr.rfqs.get()
    rfq.vendors.set(vendors[:3])
    act("procurement", pwf.rfq_send, rfq)
    price_book = {"V001": {"GYP-12": "26.50", "STD-70": "9.20", "TRK-70": "7.80"},
                  "V002": {"GYP-12": "27.75", "STD-70": "8.90", "TRK-70": "7.95"},
                  "V003": {"GYP-12": "29.00", "STD-70": "9.60", "TRK-70": "8.40"}}
    for vq, lead_time in zip(rfq.quotes.order_by("vendor__code"), (7, 10, 5)):
        vq.lead_time_days = lead_time
        vq.save()
        for ql in vq.lines.select_related("rfq_line__product"):
            ql.rate = D(price_book[vq.vendor.code].get(ql.rfq_line.product.code, "0"))
            ql.save()
        vq.recalc()
    best = rfq.quotes.get(vendor__code="V001")
    act("procurement", pwf.quote_select, best)
    po = PurchaseOrder.objects.get(quote=best)
    po.date = start + timedelta(days=16)
    po.expected_date = start + timedelta(days=23)
    po.save()
    act("procurement", pwf.po_submit, po)
    act("procurement", pwf.po_approve, po)
    if po.status == "pending_approval":
        act("sm", pwf.po_approve, po)
    act("procurement", pwf.po_send, po)
    act("store", pwf.po_receive, po)
    grn = po.receipts.get()
    grn.date = start + timedelta(days=22)
    grn.delivery_note = "DN-55871"
    grn.inspected_by = "Ali (store)"
    grn.save()
    line = grn.lines.get(product=P["GYP-12"])
    line.accepted_qty = line.received_qty - 12
    line.rejected_qty = D("12")
    line.qc_notes = "12 sheets broken edges"
    line.save()
    act("store", iwf.grn_post, grn)
    act("store", iwf.grn_return, grn)
    ret = grn.returns.get()
    act("store", pwf.return_post, ret)
    act("store", iwf.grn_landed_cost, grn)
    lc = grn.landed_costs.get()
    lc.vendor = vendors[4]
    lc.save()
    LandedCostCharge.objects.create(landed_cost=lc, charge_type="freight", description="Delivery to Al Quoz", amount=D("850"))
    act("store", pwf.landed_post, lc)
    # replacement delivery for the rejected sheets
    act("store", pwf.po_receive, po)
    grn2 = po.receipts.filter(status="draft").get()
    grn2.date = start + timedelta(days=27)
    grn2.save()
    act("store", iwf.grn_post, grn2)
    say(f"Procurement: {mr.number} shortfall → {pr.number} → {rfq.number} (3 quotes) → {po.number} ({po.get_status_display()}) "
        f"→ {grn.number} (12 rejected) → {ret.number} → {lc.number} → {grn2.number}")

    # vendor invoice → 3-way match → payment
    act("accounts", pwf.po_invoice, po, "EGT-INV-20931")
    vinv = VendorInvoice.objects.get(purchase_order=po)
    vinv.date = start + timedelta(days=30)
    vinv.save()
    act("accounts", awf.vinv_match, vinv)
    act("accounts", awf.vinv_post, vinv)
    bank = BankAccount.objects.get(account__code="1110")
    pay = VendorPayment.objects.create(vendor=po.vendor, bank_account=bank, mode="cheque", amount=vinv.total,
                                       date=start + timedelta(days=45), cheque_date=start + timedelta(days=45))
    VendorPaymentAllocation.objects.create(payment=pay, invoice=vinv, amount=vinv.total)
    act("accounts", awf.vpay_submit, pay)
    act("accounts", awf.vpay_approve, pay)
    if pay.status == "pending_approval":
        act("sm", awf.vpay_approve, pay)
    act("accounts", awf.vpay_post, pay)
    say(f"AP: {vinv.number} matched & posted, paid by cheque {pay.cheque_no}")

    # subcontract PO (non-stock) for MEP
    sub_pr = PurchaseRequisition.objects.create(source="manual", project=project, warehouse=main,
                                                date=start + timedelta(days=20))
    from procurement.models import PurchaseRequisitionLine
    PurchaseRequisitionLine.objects.create(requisition=sub_pr, product=P["SUB-MEP"], qty=1, estimated_rate=D("118000"),
                                           description="MEP modifications Level 12")
    act("procurement", pwf.pr_submit, sub_pr)
    act("pm", pwf.pr_approve, sub_pr)
    act("procurement", pwf.pr_direct_po, sub_pr, "V004")
    sub_po = sub_pr.orders.get()
    act("procurement", pwf.po_submit, sub_po)
    act("procurement", pwf.po_approve, sub_po)
    act("sm", pwf.po_approve, sub_po)
    act("procurement", pwf.po_send, sub_po)
    act("pm", pwf.po_receive, sub_po)
    sub_grn = sub_po.receipts.get()
    gl = sub_grn.lines.get()
    gl.received_qty = gl.accepted_qty = D("0.4")
    gl.qc_notes = "40% of MEP works certified"
    gl.save()
    sub_grn.date = today - timedelta(days=10)
    sub_grn.save()
    act("pm", iwf.grn_post, sub_grn)

    # issue to project, return surplus, transfer
    act("store", iwf.mr_internal_request, mr)
    ir = mr.internal_requests.get()
    act("store", iwf.ir_release, ir)
    act("store", iwf.ir_issue, ir)
    siv = ir.issues.get()
    siv.date = start + timedelta(days=28)
    siv.issued_to = "Site foreman"
    siv.save()
    act("store", iwf.siv_post, siv)
    mr2 = MaterialRequisition.objects.create(project=project, warehouse=main, date=start + timedelta(days=40))
    for code, qty in [("TIL-60", 30), ("ADH-25", 40), ("MDF-18", 20), ("PNT-EM", 15), ("HNG-01", 120), ("CT-600", 60)]:
        MaterialRequisitionLine.objects.create(requisition=mr2, product=P[code], qty=qty)
    act("pm", iwf.mr_submit, mr2)
    act("store", iwf.mr_internal_request, mr2)
    ir2 = mr2.internal_requests.get()
    act("store", iwf.ir_issue, ir2)
    siv2 = ir2.issues.get()
    siv2.date = start + timedelta(days=41)
    siv2.save()
    act("store", iwf.siv_post, siv2)
    pret = ProjectReturn.objects.create(project=project, warehouse=main, date=start + timedelta(days=50))
    ProjectReturnLine.objects.create(ret=pret, product=P["HNG-01"], qty=20, condition="Unused, boxed")
    act("store", iwf.project_return_post, pret)
    tr = StockTransfer.objects.create(from_warehouse=main, to_warehouse=site, date=start + timedelta(days=52))
    StockTransferLine.objects.create(transfer=tr, product=P["SCR-25"], qty=10)
    act("store", iwf.transfer_post, tr)
    say(f"Inventory: {siv.number}, {siv2.number} issued to {project.code}; {pret.number} returned; {tr.number} MAIN→SITE")

    # --- variation order ----------------------------------------------------------------
    vo = VariationOrder.objects.create(project=project, title="Additional glass partition, meeting room",
                                       reason="Client added a glazed meeting room", client_reference="ANRE-VO-01",
                                       date=start + timedelta(days=45))
    VariationLine.objects.create(variation=vo, category="subcontract", description="Frameless glass partition",
                                 qty=24, uom="sqm", unit_cost=D("520"), selling_rate=D("690"))
    VariationLine.objects.create(variation=vo, category="labour", description="Installation & making good",
                                 qty=80, uom="hr", unit_cost=D("16"), selling_rate=D("25"))
    vo.recalc()
    act("pm", pui.vo_submit, vo)
    act("sm", pui.vo_approve, vo)
    say(f"Variation {vo.number} approved (+{vo.selling_total:,.2f})")

    # --- HRMS ---------------------------------------------------------------------------
    T = {t.name: t for t in Trade.objects.all()}
    dept = Department.objects.get(name="Projects")
    visa = VisaQuota.objects.first()
    rooms = list(Room.objects.all())
    staff = [
        ("E001", "Rajesh Kumar", "direct", "Foreman", "Foreman", "4500", "1500", "500", False, "B", "1800"),
        ("E002", "Mohammed Aslam", "direct", "Carpenter", "Skilled Labour", "2200", "0", "200", False, "C", "1500"),
        ("E003", "Suresh Babu", "direct", "Gypsum fixer", "Skilled Labour", "2000", "0", "200", True, "C", "1500"),
        ("E004", "Imran Khan", "direct", "Painter", "Skilled Labour", "1900", "0", "200", False, "C", "1500"),
        ("E005", "Bikash Thapa", "hired", "Helper", "Helper", "0", "0", "0", False, "none", "0"),
        ("E006", "Anil Shrestha", "hired", "Tile mason", "Skilled Labour", "0", "0", "0", False, "none", "0"),
    ]
    emps = []
    for i, (code, name, typ, trade, desig, basic, housing, transport, cash_ot, ticket, ticket_amt) in enumerate(staff):
        e = Employee.objects.create(
            code=code, name=name, employee_type=typ, department=dept, primary_trade=T[trade],
            designation=Designation.objects.get(name=desig), basic_salary=D(basic), housing_allowance=D(housing),
            transport_allowance=D(transport), food_deduction=D("150") if typ == "direct" else 0,
            hourly_rate=D("12") if typ == "hired" else 0, cash_ot=cash_ot, ticket_category=ticket,
            ticket_amount=D(ticket_amt), joining_date=today - timedelta(days=400 * (6 - i)),
            nationality="India" if i < 4 else "Nepal", iban=f"AE07026000101234567{8900 + i}",
            bank_routing_code="302620122", wps_person_id=f"1000{i}2345678", visa_quota=visa if typ == "direct" else None)
        e.trades.add(T[trade])
        if code == "E002":
            e.trades.add(T["Helper"])
        EmployeeDocument.objects.create(employee=e, doc_type="passport", number=f"P{1234567 + i}",
                                        expiry_date=today + timedelta(days=30 + 200 * i))
        EmployeeDocument.objects.create(employee=e, doc_type="visa", number=f"201/2025/{77000 + i}",
                                        expiry_date=today + timedelta(days=45 + 90 * i))
        RoomAllocation.objects.create(room=rooms[i // 4], employee=e, date_from=e.joining_date)
        emps.append(e)
    mob = Mobilization.objects.create(project=project, kind="bulk", job="Level 12 partitions & finishes",
                                      date_from=start + timedelta(days=12), date=start + timedelta(days=12))
    for e in emps:
        MobilizationLine.objects.create(mobilization=mob, employee=e, trade=e.primary_trade)
    act("hr", hui.mob_confirm, mob)
    # attendance for the previous calendar month (working days), with some OT, a Friday and an absence
    first_this = today.replace(day=1)
    last_month_end = first_this - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    d = last_month_start
    while d <= last_month_end:
        if d.weekday() != 6:  # Sunday off
            sheet = AttendanceSheet.objects.create(project=project, date=d)
            for e in emps:
                status = "A" if (e.code == "E004" and d.day in (8, 9)) else "P"
                hours = D("10") if d.weekday() in (0, 2) else D("8")
                if d.weekday() == 4:
                    hours = D("6")
                Attendance.objects.create(sheet=sheet, employee=e, trade=e.primary_trade, status=status,
                                          hours_worked=hours if status == "P" else 0)
            sheet.recalc()
            act("pm", hui.sheet_confirm, sheet)
        d += timedelta(days=1)
    annual = LeaveType.objects.get(is_annual_leave=True)
    lv = LeaveApplication.objects.create(employee=emps[1], leave_type=annual, date_from=first_this + timedelta(days=40),
                                         date_to=first_this + timedelta(days=69), leave_salary_in_advance=True)
    act("hr", hui.leave_approve, lv)
    loan = Loan.objects.create(employee=emps[2], amount=D("3000"), monthly_installment=D("500"),
                               date=last_month_start, remarks="Family emergency")
    act("hr", hui.loan_disburse, loan)
    Deduction.objects.create(employee=emps[3], deduction_type="fine", year=last_month_end.year,
                             month=last_month_end.month, amount=D("100"), description="Late to site x2")
    run = PayrollRun.objects.create(year=last_month_end.year, month=last_month_end.month, date=last_month_end)
    act("hr", hui.payroll_process, run)
    act("accounts", hui.payroll_post, run)
    act("accounts", hui.payroll_paid, run)
    say(f"HRMS: 6 employees mobilized, {AttendanceSheet.objects.count()} attendance sheets, payroll {run} "
        f"net {run.total_net:,.2f} (cash OT {run.total_cash_ot:,.2f})")

    # --- billing & receipts ------------------------------------------------------------
    adv = CustomerInvoice.objects.create(contract=contract, customer=cust, invoice_type="advance",
                                         date=contract.date + timedelta(days=2), description="10% advance payment")
    adv.recalc()
    act("accounts", awf.invoice_post, adv)
    r1 = Receipt.objects.create(customer=cust, project=project, mode="transfer", bank_account=bank, amount=adv.total,
                                date=adv.date + timedelta(days=12), reference="TT ANRE 88123")
    ReceiptAllocation.objects.create(receipt=r1, invoice=adv, amount=adv.total)
    act("accounts", awf.receipt_post, r1)
    inv1 = CustomerInvoice.objects.create(contract=contract, customer=cust, invoice_type="progress",
                                          cumulative_percent=D("30"), date=start + timedelta(days=45),
                                          description="Progress claim 1 (30%)")
    inv1.recalc()
    act("accounts", awf.invoice_post, inv1)
    r2 = Receipt.objects.create(customer=cust, project=project, mode="pdc", bank_account=bank, amount=inv1.total,
                                date=start + timedelta(days=55), cheque_no="004512", cheque_date=today - timedelta(days=3))
    ReceiptAllocation.objects.create(receipt=r2, invoice=inv1, amount=inv1.total)
    act("accounts", awf.receipt_post, r2)
    act("accounts", awf.receipt_clear, r2)
    inv2 = CustomerInvoice.objects.create(contract=contract, customer=cust, invoice_type="progress",
                                          cumulative_percent=D("55"), date=today - timedelta(days=5),
                                          description="Progress claim 2 (55% incl. VO-1)")
    inv2.recalc()
    act("accounts", awf.invoice_post, inv2)
    r3 = Receipt.objects.create(customer=cust, project=project, mode="pdc", bank_account=bank, amount=inv2.total,
                                date=today - timedelta(days=1), cheque_no="004613", cheque_date=today + timedelta(days=30))
    ReceiptAllocation.objects.create(receipt=r3, invoice=inv2, amount=inv2.total)
    act("accounts", awf.receipt_post, r3)
    say(f"Billing: {adv.number} advance, {inv1.number} 30%, {inv2.number} 55%; PDC {r3.cheque_no} in hand")

    # --- fixed assets, depreciation, budgets, bank statement ------------------------------
    veh = AssetCategory.objects.get(name="Vehicles & machinery")
    it = AssetCategory.objects.get(name__startswith="Furniture")
    FixedAsset.objects.create(code="FA-001", name="Pickup truck Toyota Hilux", category=veh, purchase_date=start,
                              cost=D("98000"), salvage_value=D("18000"), useful_life_months=60, registration_no="Dubai L 45821")
    FixedAsset.objects.create(code="FA-002", name="Scissor lift 8m", category=veh, purchase_date=start, cost=D("42000"),
                              useful_life_months=60, project=project)
    FixedAsset.objects.create(code="FA-003", name="Office laptops (10)", category=it, purchase_date=start, cost=D("36000"),
                              useful_life_months=36)
    from core.services import audit  # noqa: F401
    from accounts.services import ctl, post_journal

    c = ctl()
    post_journal(start, [
        {"account": veh.asset_account, "debit": D("140000")}, {"account": it.asset_account, "debit": D("36000")},
        {"account": bank.account, "credit": D("176000"), "description": "Asset purchases"}], "PV", "Fixed asset purchases")
    post_journal(start - timedelta(days=1), [
        {"account": bank.account, "debit": D("1500000"), "description": "Capital introduced"},
        {"account": Account.objects.get(code="3100"), "credit": D("1500000")}], "OB", "Opening balances")
    post_journal(last_month_end, [
        {"account": Account.objects.get(code="6200"), "debit": D("25000"), "description": "Office & warehouse rent"},
        {"account": Account.objects.get(code="6300"), "debit": D("3800"), "description": "DEWA & telecom"},
        {"account": c.vat_input, "debit": D("1440")},
        {"account": bank.account, "credit": D("30240")}], "PV", "Monthly overheads")
    for period_end in (last_month_end,):
        dep = DepreciationRun.objects.create(period_end=period_end, date=period_end)
        act("accounts", awf.dep_compute, dep)
        act("accounts", awf.dep_post, dep)
    for code, monthly in [("6200", "25000"), ("6300", "4000"), ("6800", "3000"), ("6700", "6000")]:
        Budget.objects.create(fiscal_year=today.year, account=Account.objects.get(code=code),
                              **{m: D(monthly) for m in Budget.MONTHS})
    Budget.objects.create(fiscal_year=today.year, account=Account.objects.get(code="4100"),
                          **{m: D("150000") for m in Budget.MONTHS})
    for d_, desc, amount in [(start - timedelta(days=1), "Capital injection", "1500000"),
                             (start + timedelta(days=1), "Vehicle & IT purchases", "-176000"),
                             (adv.date + timedelta(days=12), "TT ANRE 88123", str(adv.total)),
                             (today - timedelta(days=2), "Cheque 004512 clearing", str(inv1.total))]:
        BankStatementLine.objects.create(bank_account=bank, date=d_, description=desc, amount=D(amount))
    matched = auto_match(bank)
    say(f"Accounts: 3 fixed assets + depreciation, budgets, bank statement ({matched} lines auto-matched)")

    # a pending PO for the dashboard
    pr3 = PurchaseRequisition.objects.create(source="manual", project=project, warehouse=main)
    PurchaseRequisitionLine.objects.create(requisition=pr3, product=P["CPT-01"], qty=500, estimated_rate=D("84"))
    act("procurement", pwf.pr_submit, pr3)
    project.progress_percent = D("55")
    project.save()
    say("Demo scenario complete.")
