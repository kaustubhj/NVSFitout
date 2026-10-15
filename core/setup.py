"""Master data a new installation needs: roles, users, company, chart of accounts, control accounts,
warehouses, products, approval rules, HR masters."""
from datetime import date
from decimal import Decimal as D

from django.contrib.auth.models import Group, User

from .models import ApprovalRule, Company, Currency

ROLES = ["Sales", "Estimator", "Project Manager", "Senior Manager", "Procurement", "Storekeeper", "HR", "Accounts"]

DEMO_USERS = [
    ("sales", "Sara", "Sales", ["Sales"]),
    ("estimator", "Omar", "Estimator", ["Estimator", "Sales"]),
    ("pm", "Priya", "Project Manager", ["Project Manager", "Estimator", "Sales", "Storekeeper"]),
    ("sm", "Khalid", "Senior Manager", ["Senior Manager", "Project Manager"]),
    ("procurement", "Rahul", "Procurement", ["Procurement"]),
    ("store", "Ali", "Storekeeper", ["Storekeeper"]),
    ("hr", "Fatima", "HR", ["HR"]),
    ("accounts", "Anoop", "Accounts", ["Accounts"]),
]

COA = [
    # code, name, type, parent, is_group, cost_category, is_direct
    ("1000", "Assets", "asset", None, True, "", False),
    ("1100", "Cash in hand", "asset", "1000", False, "", False),
    ("1110", "Bank - Current account", "asset", "1000", False, "", False),
    ("1120", "Bank - Payroll account", "asset", "1000", False, "", False),
    ("1200", "Accounts receivable", "asset", "1000", False, "", False),
    ("1210", "Retention receivable", "asset", "1000", False, "", False),
    ("1220", "PDC receivable", "asset", "1000", False, "", False),
    ("1230", "Employee loans & advances", "asset", "1000", False, "", False),
    ("1240", "VAT input", "asset", "1000", False, "", False),
    ("1250", "Prepayments & deposits", "asset", "1000", False, "", False),
    ("1300", "Inventory - materials", "asset", "1000", False, "", False),
    ("1310", "Inventory - consumables", "asset", "1000", False, "", False),
    ("1500", "Fixed assets", "asset", "1000", True, "", False),
    ("1510", "Vehicles & machinery", "asset", "1500", False, "", False),
    ("1511", "Acc. depreciation - vehicles & machinery", "asset", "1500", False, "", False),
    ("1520", "Buildings", "asset", "1500", False, "", False),
    ("1521", "Acc. depreciation - buildings", "asset", "1500", False, "", False),
    ("1530", "Furniture, fittings & IT", "asset", "1500", False, "", False),
    ("1531", "Acc. depreciation - furniture & IT", "asset", "1500", False, "", False),
    ("2000", "Liabilities", "liability", None, True, "", False),
    ("2100", "Accounts payable", "liability", "2000", False, "", False),
    ("2110", "Goods received not invoiced (GRNI)", "liability", "2000", False, "", False),
    ("2120", "PDC payable", "liability", "2000", False, "", False),
    ("2130", "Payroll payable", "liability", "2000", False, "", False),
    ("2140", "VAT output", "liability", "2000", False, "", False),
    ("2150", "Customer advances", "liability", "2000", False, "", False),
    ("2160", "EOS provision", "liability", "2000", False, "", False),
    ("2170", "Landed cost clearing", "liability", "2000", False, "", False),
    ("2200", "Bank loans", "liability", "2000", False, "", False),
    ("3000", "Equity", "equity", None, True, "", False),
    ("3100", "Share capital", "equity", "3000", False, "", False),
    ("3200", "Retained earnings", "equity", "3000", False, "", False),
    ("4000", "Income", "income", None, True, "", False),
    ("4100", "Contract revenue", "income", "4000", False, "", False),
    ("4200", "Other income", "income", "4000", False, "", False),
    ("4210", "Payroll recoveries (food, fines)", "income", "4000", False, "", False),
    ("5000", "Direct costs", "expense", None, True, "", True),
    ("5100", "Material cost", "expense", "5000", False, "material", True),
    ("5200", "Direct labour", "expense", "5000", False, "labour", True),
    ("5300", "Subcontract cost", "expense", "5000", False, "subcontract", True),
    ("5400", "Other direct cost", "expense", "5000", False, "other", True),
    ("5500", "Purchase price variance", "expense", "5000", False, "material", True),
    ("6000", "Overheads", "expense", None, True, "", False),
    ("6100", "Staff salaries", "expense", "6000", False, "overhead", False),
    ("6200", "Rent", "expense", "6000", False, "overhead", False),
    ("6300", "Utilities & telecom", "expense", "6000", False, "overhead", False),
    ("6400", "Depreciation", "expense", "6000", False, "overhead", False),
    ("6500", "Stock adjustments & shrinkage", "expense", "6000", False, "overhead", False),
    ("6600", "Exchange difference", "expense", "6000", False, "overhead", False),
    ("6700", "General & administrative", "expense", "6000", False, "overhead", False),
    ("6800", "Vehicle running", "expense", "6000", False, "overhead", False),
]

CONTROL = {
    "receivable": "1200", "payable": "2100", "grni": "2110", "inventory": "1300", "vat_output": "2140",
    "vat_input": "1240", "retention_receivable": "1210", "customer_advance": "2150", "contract_revenue": "4100",
    "payroll_payable": "2130", "labour_cost": "5200", "staff_cost": "6100", "material_cost": "5100",
    "subcontract_cost": "5300", "pdc_receivable": "1220", "pdc_payable": "2120", "stock_adjustment": "6500",
    "landed_cost_clearing": "2170", "price_variance": "5500", "depreciation_expense": "6400",
    "employee_loans": "1230", "cash": "1100", "retained_earnings": "3200", "exchange_difference": "6600",
    "payroll_recoveries": "4210",
}

PRODUCTS = [
    # code, name, category, uom, std cost, reorder level, reorder qty, stock?
    ("GYP-12", "Gypsum board 12.5mm 1200x2400", "Drywall & ceilings", "sht", "28.00", 100, 300, True),
    ("STD-70", "Metal stud 70mm x 3m", "Drywall & ceilings", "pcs", "9.50", 200, 600, True),
    ("TRK-70", "Metal track 70mm x 3m", "Drywall & ceilings", "pcs", "8.00", 100, 300, True),
    ("CT-600", "Ceiling tile 600x600 mineral fibre", "Drywall & ceilings", "pcs", "12.00", 150, 400, True),
    ("PNT-EM", "Emulsion paint 18L white", "Paint & finishes", "pail", "145.00", 20, 60, True),
    ("PNT-PR", "Primer 18L", "Paint & finishes", "pail", "110.00", 10, 30, True),
    ("TIL-60", "Porcelain tile 600x600", "Flooring", "sqm", "65.00", 100, 300, True),
    ("CPT-01", "Carpet tile 500x500", "Flooring", "sqm", "85.00", 50, 200, True),
    ("ADH-25", "Tile adhesive 25kg", "Flooring", "bag", "22.00", 40, 120, True),
    ("MDF-18", "MDF board 18mm 1220x2440", "Joinery", "sht", "95.00", 30, 80, True),
    ("VEN-OK", "Oak veneer sheet", "Joinery", "sht", "180.00", 10, 30, True),
    ("HNG-01", "Soft-close hinge", "Joinery", "pcs", "6.50", 100, 300, True),
    ("SCR-25", "Drywall screws 25mm (1000)", "Consumables", "box", "18.00", 30, 100, True),
    ("SUB-MEP", "MEP subcontract works", "Subcontract", "ls", "0.00", 0, 0, False),
    ("SUB-GLZ", "Glazing subcontract works", "Subcontract", "ls", "0.00", 0, 0, False),
]


def ensure_masters(stdout=None):
    say = (lambda m: stdout.write(m)) if stdout else (lambda m: None)
    from accounts.models import Account, AssetCategory, BankAccount, ControlAccounts
    from hrms.models import Camp, Department, Designation, LeaveType, PublicHoliday, Room, Trade, VisaQuota
    from inventory.models import Bin, Product, ProductCategory, UoM, Warehouse
    from sales.models import TermsTemplate

    company = Company.get()
    if not company.trn:
        company.name = "Fit-Out Interiors LLC"
        company.trn = "100123456700003"
        company.address = "Office 1204, Business Bay\nDubai, United Arab Emirates"
        company.phone = "+971 4 000 0000"
        company.email = "info@fitout.example"
        company.employer_eid = "0000123456789"
        company.employer_bank_routing = "302620122"
        company.save()
    for code, name, rate in [("AED", "UAE Dirham", "1"), ("USD", "US Dollar", "3.6725"), ("EUR", "Euro", "4.02")]:
        Currency.objects.get_or_create(code=code, defaults={"name": name, "rate": D(rate)})
    groups = {r: Group.objects.get_or_create(name=r)[0] for r in ROLES}
    say(f"Roles: {', '.join(ROLES)}")

    accounts = {}
    for code, name, typ, parent, is_group, cat, direct in COA:
        acc, _ = Account.objects.get_or_create(code=code, defaults={
            "name": name, "type": typ, "parent": accounts.get(parent), "is_group": is_group,
            "cost_category": cat, "is_direct_cost": direct})
        accounts[code] = acc
    ctl = ControlAccounts.get()
    for field, code in CONTROL.items():
        if getattr(ctl, f"{field}_id") is None:
            setattr(ctl, field, accounts[code])
    ctl.save()
    say(f"Chart of accounts: {len(COA)} accounts, control accounts mapped")

    BankAccount.objects.get_or_create(account=accounts["1110"], defaults={
        "name": "Current account", "bank_name": "Emirates NBD", "account_number": "1012345678901",
        "iban": "AE070260001012345678901", "swift": "EBILAEAD"})
    BankAccount.objects.get_or_create(account=accounts["1120"], defaults={
        "name": "Payroll account", "bank_name": "Emirates NBD", "account_number": "1012345678902",
        "iban": "AE070260001012345678902", "swift": "EBILAEAD", "next_cheque_no": 500001})
    for name, a, acc, exp, life in [("Vehicles & machinery", "1510", "1511", "6400", 60),
                                    ("Buildings", "1520", "1521", "6400", 240),
                                    ("Furniture, fittings & IT", "1530", "1531", "6400", 36)]:
        AssetCategory.objects.get_or_create(name=name, defaults={
            "asset_account": accounts[a], "accumulated_account": accounts[acc], "expense_account": accounts[exp],
            "useful_life_months": life})

    main, _ = Warehouse.objects.get_or_create(code="MAIN", defaults={"name": "Main Store", "location": "Al Quoz Industrial 3"})
    site, _ = Warehouse.objects.get_or_create(code="SITE", defaults={"name": "Site Store", "location": "Project sites",
                                                                       "is_site_store": True})
    for wh, codes in ((main, ["A-01", "A-02", "B-01", "B-02", "YARD"]), (site, ["S-01", "S-02"])):
        for c in codes:
            Bin.objects.get_or_create(warehouse=wh, code=c)
    uoms = {}
    for code, name in [("pcs", "Pieces"), ("sht", "Sheet"), ("sqm", "Square metre"), ("pail", "Pail"), ("bag", "Bag"),
                       ("box", "Box"), ("ls", "Lump sum"), ("m", "Metre"), ("nos", "Numbers")]:
        uoms[code] = UoM.objects.get_or_create(code=code, defaults={"name": name})[0]
    cats = {}
    for name in ["Drywall & ceilings", "Paint & finishes", "Flooring", "Joinery", "Consumables", "Subcontract"]:
        cats[name] = ProductCategory.objects.get_or_create(name=name, kind="material")[0]
    for name in ["Carpentry", "Painting", "Tiling", "Gypsum"]:
        ProductCategory.objects.get_or_create(name=name, kind="trade")
    for name in ["Site consumption", "Workshop"]:
        ProductCategory.objects.get_or_create(name=name, kind="usage")
    bins = list(Bin.objects.filter(warehouse=main).order_by("code"))
    for i, (code, name, cat, uom, cost, rl, rq, is_stock) in enumerate(PRODUCTS):
        Product.objects.get_or_create(code=code, defaults={
            "name": name, "category": cats[cat], "uom": uoms[uom], "standard_cost": D(cost), "reorder_level": rl,
            "reorder_qty": rq, "is_stock": is_stock, "default_bin": bins[i % len(bins)] if is_stock else None,
            "stock_account": accounts["1310"] if cat == "Consumables" else (accounts["1300"] if is_stock else None),
            "expense_account": accounts["5300"] if not is_stock else accounts["5100"]})
    say(f"Warehouses MAIN and SITE, {len(PRODUCTS)} products")

    rules = [("quotation", 1, "Project Manager", "0", None), ("quotation", 2, "Senior Manager", "0", None),
             ("purchase_requisition", 1, "Project Manager", "0", None),
             ("purchase_order", 1, "Procurement", "0", None), ("purchase_order", 2, "Senior Manager", "50000", None),
             ("variation_order", 1, "Senior Manager", "0", None), ("stock_adjustment", 1, "Senior Manager", "0", None),
             ("vendor_payment", 1, "Accounts", "0", None), ("vendor_payment", 2, "Senior Manager", "100000", None)]
    if not ApprovalRule.objects.exists():
        for doc, level, group, lo, hi in rules:
            ApprovalRule.objects.create(doc_type=doc, level=level, group=groups[group], min_amount=D(lo), max_amount=hi)
    TermsTemplate.objects.get_or_create(name="Standard fit-out terms", defaults={"is_standard": True, "body": (
        "1. Validity: 30 days from the date of quotation.\n"
        "2. Payment: 10% advance against advance payment guarantee; monthly progress payments within 30 days of "
        "certification; 10% retention released 400 days after the final invoice.\n"
        "3. Programme: to be agreed on award; site access and power by client.\n"
        "4. Exclusions: authority fees, MEP design approvals and works not listed in the BOQ.\n"
        "5. Variations: any change in scope will be priced and approved before execution.\n"
        "6. All prices in AED, exclusive of 5% VAT.")})
    TermsTemplate.objects.get_or_create(name="Custom - design & build", defaults={"body": (
        "Design and build terms: design fee 5% payable on concept approval; balance as per standard fit-out terms.")})

    for name, hours, rate in [("Carpenter", "8", "18"), ("Painter", "8", "15"), ("Tile mason", "8", "17"),
                              ("Gypsum fixer", "8", "16"), ("Electrician", "8", "20"), ("Helper", "8", "11"),
                              ("Foreman", "9", "25")]:
        Trade.objects.get_or_create(name=name, defaults={"standard_hours": D(hours), "labour_rate": D(rate)})
    for name in ["Projects", "Estimation", "Procurement", "Stores", "HR & Admin", "Finance"]:
        Department.objects.get_or_create(name=name)
    for name, jd in [("Project Manager", "Leads delivery of fit-out projects: programme, cost, quality and client."),
                     ("Site Engineer", "Supervises site works and subcontractors; prepares MRs and progress."),
                     ("Foreman", "Runs the site gangs and daily attendance."),
                     ("Skilled Labour", "Carries out trade works as per drawings and method statements."),
                     ("Helper", "Assists skilled trades; material handling."),
                     ("Storekeeper", "Receives, inspects, stores and issues material.")]:
        Designation.objects.get_or_create(name=name, defaults={"job_description": jd})
    for name, paid, days, annual in [("Annual leave", True, 30, True), ("Sick leave", True, 15, False),
                                     ("Unpaid leave", False, 0, False), ("Emergency leave", True, 5, False)]:
        LeaveType.objects.get_or_create(name=name, defaults={"paid": paid, "annual_entitlement_days": days,
                                                             "is_annual_leave": annual})
    for d, name in [(date(2026, 1, 1), "New Year's Day"), (date(2026, 3, 20), "Eid Al Fitr"),
                    (date(2026, 5, 27), "Eid Al Adha"), (date(2026, 12, 2), "National Day"),
                    (date(2026, 12, 3), "National Day holiday")]:
        PublicHoliday.objects.get_or_create(date=d, defaults={"name": name})
    camp, created = Camp.objects.get_or_create(name="Sonapur Camp 1", defaults={"location": "Muhaisnah 2"})
    if created:
        for n in range(1, 7):
            Room.objects.create(camp=camp, number=f"R{n:02d}", capacity=8)
    VisaQuota.objects.get_or_create(establishment="Fit-Out Interiors LLC", designation=None,
                                    defaults={"quota": 60, "notes": "Main establishment card"})
    say("HR masters: trades, departments, designations, leave types, holidays, camp, visa quota")
    return groups


def ensure_users(groups, password, stdout=None, reset=False):
    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser("admin", "admin@fitout.example", password, first_name="Admin")
    for username, first, last, roles in DEMO_USERS:
        user, created = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last})
        if created or reset:
            user.set_password(password)
            user.save()
        user.groups.set([groups[r] for r in roles])
    if reset:
        admin = User.objects.get(username="admin")
        admin.set_password(password)
        admin.is_active = admin.is_staff = admin.is_superuser = True
        admin.save()
    if stdout:
        stdout.write(f"Users: admin + {', '.join(u[0] for u in DEMO_USERS)}" + (" (passwords reset)" if reset else ""))
