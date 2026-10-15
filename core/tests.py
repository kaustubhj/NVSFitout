from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from core.demo import Req, act, run_demo
from core.services import q2
from core.setup import ensure_masters, ensure_users
from core.ui import registry


class DemoScenarioTests(TestCase):
    """Runs the full cross-module scenario once and checks the books and documents."""

    @classmethod
    def setUpTestData(cls):
        ensure_users(ensure_masters(), "pw-test-123")
        run_demo()

    def test_trial_balance_balances(self):
        from accounts.models import JournalLine

        agg = JournalLine.objects.filter(entry__status="posted").aggregate(d=Sum("base_debit"), c=Sum("base_credit"))
        self.assertEqual(agg["d"], agg["c"])

    def test_stock_ledger_equals_inventory_gl(self):
        from accounts.models import Account
        from inventory.models import StockBalance, StockMove

        gl = sum(Account.objects.get(code=c).balance() for c in ("1300", "1310"))
        self.assertEqual(gl, StockBalance.objects.aggregate(v=Sum("value"))["v"])
        self.assertEqual(StockMove.objects.aggregate(v=Sum("value"))["v"], gl)

    def test_sales_flow(self):
        from sales.models import Lead, Quotation

        lead = Lead.objects.get(number="LD-00001")
        self.assertEqual(lead.status, "won")
        q = Quotation.objects.get(lead=lead)
        self.assertEqual(q.status, "accepted")
        self.assertEqual(q.revision, 1)
        self.assertEqual(q.revisions.count(), 1)
        project = q.contract.projects.get()
        self.assertGreater(project.budget_material, 0)
        self.assertEqual(project.manpower.count(), 6)

    def test_estimation_sheet_reaches_store_without_prices(self):
        from inventory.models import MaterialRequisition

        sheet = MaterialRequisition.objects.get(is_planning_sheet=True)
        self.assertEqual(sheet.lines.count(), 9)
        self.assertFalse(hasattr(sheet.lines.first(), "unit_cost"))

    def test_procurement_flow(self):
        from procurement.models import PurchaseOrder

        po = PurchaseOrder.objects.get(number="PO-00001")
        self.assertEqual(po.vendor.code, "V001")  # cheapest quote selected
        self.assertEqual(po.status, "received")
        gyp = po.lines.get(product__code="GYP-12")
        self.assertEqual(gyp.received_qty, gyp.qty)
        self.assertEqual(po.vendor_invoices.get().status, "posted")

    def test_payroll(self):
        from hrms.models import PayrollRun

        run = PayrollRun.objects.get()
        self.assertEqual(run.status, "paid")
        self.assertEqual(run.payslips.count(), 6)
        cash_ot = run.payslips.get(employee__code="E003")
        self.assertGreater(cash_ot.cash_ot_amount, 0)
        self.assertEqual(cash_ot.ot_amount, 0)
        absent = run.payslips.get(employee__code="E004")
        self.assertLess(absent.days_payable, 30)
        allocated = sum(c.amount for s in run.payslips.all() for c in s.costs.all())
        self.assertEqual(allocated, run.total_gross + run.total_cash_ot)

    def test_project_costing_and_billing(self):
        from projects.models import Project

        p = Project.objects.get(code__startswith="P")
        data = p.profitability()
        self.assertGreater(data["actual"]["material"], 0)
        self.assertGreater(data["actual"]["labour"], 0)
        self.assertGreater(data["actual"]["subcontract"], 0)
        self.assertGreater(data["revenue"], 0)
        self.assertEqual(p.vo_totals()[0], D("18560.00"))
        inv = p.customer_invoices.filter(invoice_type="progress").order_by("id")
        first, second = inv
        self.assertGreater(first.retention_amount, 0)
        self.assertGreater(first.advance_recovery, 0)
        value = p.contract.revised_value
        self.assertEqual(first.gross_amount, q2(value * D("0.30")))
        self.assertEqual(first.gross_amount + second.gross_amount, q2(value * D("0.55")))
        self.assertEqual(first.retention_amount, q2(first.gross_amount * D("0.10")))

    def test_every_screen_and_report_renders(self):
        self.client.force_login(User.objects.get(username="admin"))
        self.assertEqual(self.client.get("/").status_code, 200)
        for mod in registry.ordered():
            self.assertEqual(self.client.get(reverse("erp-module", args=[mod.key])).status_code, 200, mod.key)
            for screen in mod.screens.values():
                url = screen.url()
                self.assertEqual(self.client.get(url).status_code, 200, url)
                self.assertEqual(self.client.get(url + "?export=csv").status_code, 200, url)
                if screen.can_create:
                    self.assertEqual(self.client.get(url + "new/").status_code, 200, url + "new/")
                for obj in screen.model._default_manager.all()[:3]:
                    detail = screen.url("detail", pk=obj.pk)
                    self.assertEqual(self.client.get(detail).status_code, 200, detail)
                    r = self.client.get(detail + "edit/")
                    self.assertIn(r.status_code, (200, 302), detail)
                    if screen.print_template:
                        self.assertEqual(self.client.get(detail + "print/").status_code, 200, detail)
            for _, _, name in mod.links:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_reports_with_parameters(self):
        from accounts.models import Account
        from projects.models import Project
        from sales.models import Customer

        self.client.force_login(User.objects.get(username="accounts"))
        acc = Account.objects.get(code="1110")
        cust = Customer.objects.get(code="C001")
        p = Project.objects.first()
        for url in [f"/reports/accounts/ledger/?account={acc.pk}", f"/reports/accounts/soa/?customer={cust.pk}",
                    "/reports/accounts/trial-balance/?date_from=2026-01-01&date_to=2026-12-31",
                    "/reports/accounts/balance-sheet/?as_of=2026-12-31", "/reports/accounts/budget/?year=2026&month=9",
                    "/reports/accounts/trial-balance/?export=csv", f"/reports/projects/costing/?project={p.pk}"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_balance_sheet_balances(self):
        from accounts.reports import _balances, _pl_data
        from accounts.models import Account

        bal = _balances(None, None)
        totals = {"asset": D(0), "liability": D(0), "equity": D(0)}
        for acc in Account.objects.filter(is_group=False, type__in=totals):
            d, c = bal.get(acc.id, (D(0), D(0)))
            totals[acc.type] += d - c if acc.type == "asset" else c - d
        _, _, _, ti, td, tx = _pl_data(None, None)
        self.assertEqual(totals["asset"], totals["liability"] + totals["equity"] + ti - td - tx)


class RuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_users(ensure_masters(), "pw-test-123")

    def _quotation(self):
        from sales.models import Customer, Lead, Quotation, QuotationLine

        c = Customer.objects.create(code="T1", name="Test")
        lead = Lead.objects.create(title="T", customer=c, status="qualified")
        q = Quotation.objects.create(lead=lead, customer=c, subject="T")
        QuotationLine.objects.create(quotation=q, description="Work", qty=1, rate=D("1000"))
        q.recalc()
        return q

    def test_new_lead_form_and_prospect_becomes_customer(self):
        from django.test import Client
        from sales import workflow as swf
        from sales.models import Lead

        client = Client()
        client.login(username="sales", password="pw-test-123")
        resp = client.post("/m/sales/leads/new/", {
            "date": "2026-10-15", "salutation": "Dr.", "full_name": "Sara Ahmed", "company": "Gulf Clinics LLC",
            "email": "sara@gulfclinics.example", "mobile": "+971501112222", "website": "https://gulfclinics.example",
            "source": "website", "status": "new", "title": "Clinic fit-out", "expected_value": "250000"})
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context.get("form").errors)
        lead = Lead.objects.get(full_name="Sara Ahmed")
        self.assertIsNone(lead.customer)
        self.assertEqual(lead.contact_name, "Dr. Sara Ahmed")
        self.assertContains(client.get(f"/m/sales/leads/{lead.pk}/"), "Gulf Clinics LLC")
        lead.capability_review = "Within capability"
        lead.save()
        act("sales", swf.lead_qualify, lead)
        lead.refresh_from_db()
        self.assertEqual(lead.customer.name, "Gulf Clinics LLC")
        self.assertEqual(lead.customer.contact_person, "Dr. Sara Ahmed")
        # customer box: an existing name links, a new name creates the customer, edit shows the name
        from sales.models import Customer
        base = {"date": "2026-10-15", "full_name": "A", "mobile": "1", "source": "website", "status": "new",
                "expected_value": "0"}
        client.post("/m/sales/leads/new/", {**base, "title": "Existing", "customer": "gulf clinics llc"})
        self.assertEqual(Lead.objects.get(title="Existing").customer, lead.customer)
        client.post("/m/sales/leads/new/", {**base, "title": "Brand new", "customer": "Marina Towers"})
        new_lead = Lead.objects.get(title="Brand new")
        self.assertEqual(new_lead.customer.name, "Marina Towers")
        self.assertEqual(new_lead.customer.contact_person, "A")
        self.assertContains(client.get(f"/m/sales/leads/{new_lead.pk}/edit/"), 'value="Marina Towers"')
        self.assertContains(client.get("/m/sales/leads/new/"), '<option value="Gulf Clinics LLC">')
        before = Customer.objects.count()
        client.post("/m/sales/leads/new/", {**base, "title": "", "customer": "Never Saved Co"})  # invalid form
        self.assertEqual(Customer.objects.count(), before)
        # name and mobile are required on the form
        resp = client.post("/m/sales/leads/new/", {"date": "2026-10-15", "source": "website", "status": "new",
                                                   "title": "X", "expected_value": "0"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Lead.objects.filter(title="X").count(), 0)

    def test_quotation_needs_pm_then_sm(self):
        from sales import workflow as swf

        q = self._quotation()
        act("sales", swf.quotation_submit, q)
        self.assertEqual(q.status, "pm_approval")
        with self.assertRaises(PermissionDenied):
            act("sales", swf.quotation_approve, q)
        act("pm", swf.quotation_approve, q)
        self.assertEqual(q.status, "sm_approval")
        with self.assertRaises(PermissionDenied):
            act("pm", swf.quotation_approve, q)
        act("sm", swf.quotation_approve, q)
        self.assertEqual(q.status, "approved")

    def test_po_value_based_approval(self):
        from inventory.models import Product, Warehouse
        from procurement import workflow as pwf
        from procurement.models import PurchaseOrder, PurchaseOrderLine, Vendor

        v = Vendor.objects.create(code="TV", name="Test vendor")
        wh = Warehouse.objects.get(code="MAIN")
        small = PurchaseOrder.objects.create(vendor=v, warehouse=wh)
        PurchaseOrderLine.objects.create(order=small, product=Product.objects.get(code="GYP-12"), qty=10, rate=D("28"))
        act("procurement", pwf.po_submit, small)
        act("procurement", pwf.po_approve, small)
        self.assertEqual(small.status, "approved")
        big = PurchaseOrder.objects.create(vendor=v, warehouse=wh)
        PurchaseOrderLine.objects.create(order=big, product=Product.objects.get(code="GYP-12"), qty=3000, rate=D("28"))
        act("procurement", pwf.po_submit, big)
        act("procurement", pwf.po_approve, big)
        self.assertEqual(big.status, "pending_approval")
        act("sm", pwf.po_approve, big)
        self.assertEqual(big.status, "approved")

    def test_cannot_issue_more_than_stock(self):
        from inventory import workflow as iwf
        from inventory.models import Product, StockIssue, StockIssueLine, Warehouse
        from projects.models import Project
        from sales.models import Customer

        p = Project.objects.create(code="PX", name="X", customer=Customer.objects.create(code="X", name="X"))
        siv = StockIssue.objects.create(project=p, warehouse=Warehouse.objects.get(code="MAIN"))
        StockIssueLine.objects.create(issue=siv, product=Product.objects.get(code="GYP-12"), qty=5)
        with self.assertRaises(ValidationError):
            act("store", iwf.siv_post, siv)

    def test_overtime_rules(self):
        from hrms.models import Attendance, AttendanceSheet, Employee, PublicHoliday, Trade
        from projects.models import Project
        from sales.models import Customer

        p = Project.objects.create(code="PO1", name="OT", customer=Customer.objects.create(code="OT", name="OT"))
        e = Employee.objects.create(code="T01", name="T", basic_salary=D("3000"), primary_trade=Trade.objects.get(name="Carpenter"))
        weekday = date(2026, 10, 12)  # Monday
        friday = date(2026, 10, 16)
        holiday = date(2026, 12, 2)
        self.assertTrue(PublicHoliday.objects.filter(date=holiday).exists())
        out = {}
        for d in (weekday, friday, holiday):
            sheet = AttendanceSheet.objects.create(project=p, date=d)
            a = Attendance.objects.create(sheet=sheet, employee=e, hours_worked=D("10"))
            sheet.recalc()
            a.refresh_from_db()
            out[d] = a
        self.assertEqual(out[weekday].normal_hours, 8)
        self.assertEqual(out[weekday].normal_ot, 2)
        self.assertEqual(out[friday].friday_ot, 10)
        self.assertEqual(out[holiday].holiday_ot, 10)

    def test_gratuity(self):
        from hrms.models import Employee
        from hrms.services import gratuity

        e = Employee(basic_salary=D("3000"), joining_date=date(2016, 1, 1))
        amount, years = gratuity(e, date(2026, 1, 1))
        # 5 yrs × 21 days + ~5 yrs × 30 days at 100/day, capped at 24 months (72,000)
        self.assertGreater(amount, D("25000"))
        self.assertLessEqual(amount, D("72000"))
        self.assertEqual(gratuity(Employee(basic_salary=D("3000"), joining_date=date(2025, 6, 1)), date(2026, 1, 1))[0], 0)

    def test_three_way_match_flags_price_difference(self):
        from accounts import workflow as awf
        from accounts.models import VendorInvoice, VendorInvoiceLine
        from inventory import workflow as iwf
        from inventory.models import Product, Warehouse
        from procurement import workflow as pwf
        from procurement.models import PurchaseOrder, PurchaseOrderLine, Vendor

        v = Vendor.objects.create(code="MV", name="Match vendor")
        po = PurchaseOrder.objects.create(vendor=v, warehouse=Warehouse.objects.get(code="MAIN"))
        pl = PurchaseOrderLine.objects.create(order=po, product=Product.objects.get(code="PNT-EM"), qty=10, rate=D("145"))
        po.recalc()
        act("procurement", pwf.po_submit, po)
        act("procurement", pwf.po_approve, po)
        pwf.po_receive(Req("store"), po)
        grn = po.receipts.get()
        act("store", iwf.grn_post, grn)
        inv = VendorInvoice.objects.create(vendor=v, purchase_order=po, vendor_invoice_no="X1")
        VendorInvoiceLine.objects.create(invoice=inv, po_line=pl, qty=10, rate=D("150"))
        act("accounts", awf.vinv_match, inv)
        self.assertEqual(inv.status, "discrepancy")
        with self.assertRaises(ValidationError):
            act("accounts", awf.vinv_post, inv)
        act("sm", awf.vinv_accept_discrepancy, inv, "Price increase agreed")
        act("accounts", awf.vinv_post, inv)
        self.assertEqual(inv.status, "posted")
        pl.refresh_from_db()
        self.assertEqual(pl.invoiced_qty, 10)

    def test_login_required(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.client.force_login(User.objects.get(username="hr"))
        self.assertEqual(self.client.get(registry.get("accounts", "vouchers").url()).status_code, 403)
        self.assertEqual(self.client.get(registry.get("hrms", "employees").url()).status_code, 200)
