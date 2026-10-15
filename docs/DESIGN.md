# Fit-Out ERP — System Design

This document describes the design of the Fit-Out ERP built from the six process
diagrams (Overview, Sales & Project, Procurement, Inventory, HRMS, Accounts).
It covers the technology choices, module boundaries, data model, the
cross-module flows shown on the overview, posting rules and roles.

## 1. Technology

| Layer | Choice | Why |
|---|---|---|
| Language / framework | Python 3.12+, Django 5.2 | Mature, batteries included (auth, ORM, migrations, admin, forms), widely supported |
| Database | SQLite for development and demo, PostgreSQL for production (no code change, only `DATABASE_URL`) | Relational integrity for ledgers and stock |
| UI | Server-rendered Django templates, own CSS, a few lines of vanilla JS for line-item grids | No build step, works on any browser, fast to change |
| Auth | Django users + groups (roles) | Group-based menu visibility and approval rights |
| Exports | CSV (WPS SIF, reports), printable HTML (quotation, PO, payslip, cheque, invoice) | Print to PDF from the browser |

Base currency is **AED**. Every money document carries `currency` and
`exchange_rate`; ledgers store both the transaction amount and the base amount.
VAT defaults to 5 % (UAE).

## 2. Module boundaries

```
core        company settings, currencies, document numbering, attachments,
            audit trail, approval rules + approval log, roles
sales       customers, leads, site surveys, estimations, BOQs, T&C templates,
            quotations (+ revisions), client PO / contract
projects    projects, tasks, manpower allocation, material allocation view,
            variation orders (+ BOQ re-approval), project close
inventory   warehouses, bins, UoM, categories, products (+ account mapping),
            stock ledger, material requisition, internal request, stock issue
            voucher, GRN (store receipt voucher), stock transfer, return from
            project, stock adjustment, stock count, replenishment, dashboard
procurement vendors, purchase requisition, RFQ + vendor quotes, quote
            comparison, purchase order (value-based approval, tracking),
            landed cost, purchase return, analytics
hrms        departments, designations (job descriptions), trades, employees
            (direct / hired, multiple trades, documents), mobilization, manual
            attendance, overtime, public holidays, leave, loans, deductions,
            payroll run + payslips, EOS, air ticket, WPS file, cost allocation,
            camps / rooms / allocation, visa allocation
accounts    chart of accounts, journal vouchers (JV/PV/RV/CV), control-account
            mapping, customer invoices (advance / progressive / final /
            retention release), receipts (incl. PDC), vendor invoices (3-way
            match), vendor payments (cheque printing), bank accounts +
            reconciliation, fixed assets + depreciation, budgets, reports
```

Every module writes to the accounting ledger only through
`accounts.services.post_journal()` and to stock only through
`inventory.services.move_stock()`. Those two functions are the integration
seams; nothing else inserts ledger or stock rows.

## 3. Cross-module flows (from the overview)

```
SALES   Lead → Survey → Cost Estimation → BOQ & Margin → Quotation → Approval → Client PO/Contract
                              │ estimation sheet (no prices)                         │
                              ▼                                                       ▼
INVENTORY            Material Requisition ─► Stock Check ─► Internal Request ─► Stock Issue Voucher ─► Return/Transfer
                                                │ shortfall                                  ▲
                                                ▼                                            │ Replenishment (reorder level) ─► PR
PROCUREMENT          Purchase Requisition ─► RFQ ─► Quote Comparison ─► PO & Approval ─► PO Tracking ─► Delivery
                                                                                                  │ received
                                                                                                  ▼
INVENTORY                                                                      Inspection & GRN ─► Purchase Return
                                                                                                  │ GRN posted
                                                                                                  ▼
ACCOUNTS                                                                        3-Way Match & AP ─► Reports
PROJECT  New Project (from contract) ─► Allocation ─► Variation Order ─► Project Close (budget vs actual, GP, NP)
HRMS     Employee ─► Mobilization ─► Attendance ─► Overtime ─► Leave & Deductions ─► Payroll ─► WPS ─► Cost Allocation
                                                                                        │                 │
ACCOUNTS                                                                         Payroll Posting     Project Costing
```

Implemented as explicit actions (buttons) on documents:

| From | Action | Creates / updates |
|---|---|---|
| Lead (qualified) | *Create estimation* | Estimation linked to lead |
| Estimation (approved) | *Create BOQ* | BOQ with lines copied from estimation |
| Estimation | *Send sheet to store* | Material Requisition **without prices** for planning |
| BOQ | *Apply margin* | Selling rates = cost × (1+OH%) × (1+margin%) |
| BOQ(s) | *Create quotation* | Quotation (lines from one or more BOQs, T&C template) |
| Quotation | *Submit* → *PM approve* → *SM approve* → *Send* | Approval log, status |
| Quotation | *Revise* | New revision no., snapshot, reason, user, date |
| Quotation (accepted) | *Convert to contract* | Contract (client PO no., attachment) |
| Contract | *Create project* | Project with budget from BOQ cost split |
| Project | *Variation order* → *Approve* | Contract value + budget updated; VO BOQ lines re-approved |
| Material Requisition | *Stock check* | Available qty per line; shortfall → **Purchase Requisition** |
| Material Requisition | *Internal request* → *Issue* | Stock Issue Voucher → stock out, cost to project |
| Products below reorder | *Run replenishment* | Purchase Requisition (source = Replenishment) |
| PR (approved) | *Create RFQ* | RFQ to several vendors |
| RFQ | *Compare* → *Select vendor* | Purchase Order from chosen quote |
| PO | *Submit* | Value-based approval chain (rules by amount) |
| PO (approved/sent) | *Receive* | GRN with QC: accepted / rejected qty; PO received qty, status |
| GRN | *Post* | Stock in, Dr Inventory / Cr GRNI |
| GRN | *Landed cost* | Charges allocated to items by value, stock value updated |
| GRN | *Purchase return* | Stock out, Dr GRNI / Cr Inventory (or debit note) |
| Vendor invoice | *3-way match* | Invoice vs PO vs GRN, discrepancies flagged; post Dr GRNI / Cr AP |
| Vendor payment | *Post* / *Print cheque* | Dr AP / Cr Bank (or PDC payable) |
| Attendance | *Compute overtime* | Normal 1.25×, Friday rate, public holiday 1.5× |
| Payroll run | *Process* / *Post* / *WPS* | Payslips, Dr salaries by project / Cr payroll payable, SIF CSV |
| Contract | *Invoice* (advance / progress / final / retention) | AR, revenue, VAT, retention receivable, advance recovery |
| Receipt | *Post* / *Clear PDC* | Bank or PDC receivable, AR settled |
| Fixed assets | *Run depreciation* | Dr depreciation / Cr accumulated depreciation |
| Project | *Close* | Locks project, freezes budget vs actual, GP and NP |

## 4. Data model (main tables)

Common columns on documents: `number` (from `core.Sequence`), `date`,
`status`, `created_by`, `created_at`, `updated_at`; attachments and audit are
generic (content-type + object id).

### core
- `Company` (name, TRN, address, base currency, VAT %, Friday OT multiplier, normal OT multiplier, holiday OT multiplier, retention due days = 400)
- `Currency` (code, name, rate to base)
- `Sequence` (key, prefix, next)
- `Attachment` (generic FK, file, description)
- `AuditLog` (generic FK, user, action, changes JSON, timestamp)
- `ApprovalRule` (document type, min amount, max amount, level, group)
- `ApprovalLog` (generic FK, level, group, user, decision, comment)

### sales
- `Customer` (code, name, TRN, contact, credit days, currency)
- `Lead` (source, customer, title, location, scope, capability review, status New → Under review → Qualified/Rejected → Estimation → Quoted → Won/Lost)
- `SiteSurvey` (lead, estimator, date, findings, visits, documents)
- `Estimation` (+ `EstimationLine`: category Material/Labour/Subcontract/Other direct/Overhead, product, description, qty, UoM, unit cost)
- `BOQ` (estimation, title, overhead %, margin %) + `BOQLine` (section, description, qty, UoM, unit cost, cost category, selling rate)
- `TermsTemplate` (name, body, is standard)
- `Quotation` (customer, lead, BOQs, revision, T&C, validity, VAT, status Draft → PM approval → SM approval → Approved → Sent → Accepted / Rejected) + `QuotationLine` + `QuotationRevision` (rev no., date, user, reason, snapshot)
- `Contract` (quotation, client PO number, date, value, advance %, retention %, payment terms, document)

### projects
- `Project` (code, name, customer, contract, PM, dates, status Active/On hold/Closed, contract value, budget material/labour/subcontract/overhead)
- `ProjectTask` (project, name, dates, % complete, status)
- `ManpowerAllocation` (project, employee, trade, from, to)
- `VariationOrder` (project, description, status Draft → Submitted → Approved/Rejected, BOQ re-approved flag) + `VariationLine` (description, qty, cost rate, selling rate, cost category)

### inventory
- `Warehouse` (two seeded: Main Store, Site Store), `Bin`, `UoM`, `ProductCategory` (type: material type / trade / usage)
- `Product` (code, name, category, UoM, reorder level, reorder qty, standard cost, stock / COGS / expense accounts)
- `StockMove` (product, warehouse, bin, qty (+/−), unit cost, value, project, source document, date) — the stock ledger
- `StockBalance` (product, warehouse, qty, value) — maintained by `move_stock`, weighted average cost
- `MaterialRequisition` + lines (project, warehouse, required date, priced=false flag for estimation sheets; requested, issued, to-purchase qty)
- `InternalRequest` + lines (MR, warehouse → picking list)
- `StockIssue` (SIV) + lines (project, warehouse)
- `GoodsReceipt` (GRN) + lines (PO line, received, accepted, rejected, QC notes)
- `StockTransfer` + lines, `ProjectReturn` + lines, `StockAdjustment` + lines (reason code, approval), `StockCount` + lines (system vs counted)

### procurement
- `Vendor` (code, name, TRN, payment terms, currency, category)
- `PurchaseRequisition` + lines (source Site/Replenishment/Manual, project, cost centre, required date, status)
- `RFQ` (PR, vendors, due date) + lines; `VendorQuote` + lines (price, lead time, payment / delivery terms, selected)
- `PurchaseOrder` + lines (vendor, project, PR, quote, warehouse, currency, terms; status Draft → Pending approval → Approved → Sent → Partially received → Received → Closed / Cancelled; received / invoiced qty)
- `LandedCost` + charges (GRN, freight / duty / other, allocated by value)
- `PurchaseReturn` + lines (GRN, reason)

### hrms
- `Department`, `Designation` (job description), `Trade` (standard daily hours), `PublicHoliday`
- `Employee` (type Direct/Hired, agency, trades, department, designation, basic, housing, transport, other allowance, food deduction, OT eligible, IBAN / bank routing / WPS person ID, visa, camp room, ticket category, joining date)
- `EmployeeDocument` (type passport / visa / EID / labour card, number, expiry, file)
- `Mobilization` + lines (project, date range, employees — bulk)
- `Attendance` (date, employee, project, status, hours worked, normal OT, Friday OT, holiday OT, confirmed by fit-out team)
- `LeaveType`, `LeaveApplication` (days, leave salary in advance)
- `Loan` (amount, monthly instalment, balance), `Deduction` (fine / food / advance salary / other, month)
- `PayrollRun` + `Payslip` (earnings, OT, cash OT kept out of salary, leave salary, deductions, loan recovery, net) + `PayslipProjectCost` (allocation by attendance hours)
- `Camp`, `Room` (capacity), `RoomAllocation`; `VisaQuota` (visa allocation by company / establishment card)
- EOS (UAE gratuity: 21 days' basic per year for the first five years, 30 days thereafter, capped at two years' total) and air ticket accrual are computed services

### accounts
- `Account` (code, name, type Asset/Liability/Equity/Income/Expense, parent, is group, cost category material/labour/subcontract/overhead for project costing)
- `ControlAccounts` (single row: AR, AP, GRNI, VAT in/out, retention receivable, customer advance, revenue, payroll payable, PDC receivable/payable, stock adjustment, accumulated depreciation, …)
- `JournalEntry` (voucher type JV/PV/RV/CV/SI/PI/PAY/DEP/STK, date, currency, rate, narration, status, source document) + `JournalLine` (account, debit, credit, base debit/credit, project, customer, vendor, employee)
- `CustomerInvoice` (contract, project, type Advance/Progress/Final/Retention release, % complete, gross, advance recovery, retention, VAT, net, due date)
- `Receipt` (customer, mode cash/cheque/transfer/PDC, cheque no., cheque date, bank, PDC status) + allocations
- `VendorInvoice` + lines (PO, GRN, match status, discrepancies) and `VendorPayment` (+ allocations, cheque no.)
- `BankAccount` (GL account, IBAN), `BankStatementLine` (imported, matched journal line)
- `AssetCategory`, `FixedAsset` (cost, date, life, salvage, method), `DepreciationEntry`
- `Budget` (fiscal year, account, project optional, 12 monthly amounts)

## 5. Posting rules (double entry)

| Event | Debit | Credit |
|---|---|---|
| GRN posted | Inventory (product stock a/c) | GRNI (goods received not invoiced) |
| Landed cost | Inventory | Landed cost clearing / AP |
| Purchase return | GRNI | Inventory |
| Stock issue to project | Project material cost (product expense a/c, project tagged) | Inventory |
| Return from project | Inventory | Project material cost |
| Stock adjustment (+/−) | Inventory / Stock adjustment | Stock adjustment / Inventory |
| Vendor invoice (matched) | GRNI (+ VAT input) | Accounts payable |
| Vendor payment | Accounts payable | Bank (or PDC payable) |
| Customer invoice – advance | AR | Customer advance + VAT output |
| Customer invoice – progress | AR + Retention receivable + Customer advance (recovery) | Contract revenue + VAT output |
| Retention release invoice | AR | Retention receivable |
| Receipt | Bank (or PDC receivable) | AR |
| PDC cleared | Bank | PDC receivable |
| Payroll posted | Labour cost per project (by attendance hours) | Payroll payable (+ loans / deductions recovery) |
| Depreciation | Depreciation expense | Accumulated depreciation |

## 6. Project costing and revenue

- Budget per project and cost category comes from the BOQ cost split and is
  increased by approved variation orders.
- Actual cost = journal lines on expense accounts tagged with the project,
  grouped by the account's cost category (material / labour / subcontract / overhead).
- Gross profit = revenue − direct cost (material + labour + subcontract);
  net profit = GP − allocated overhead.
- Unbilled revenue (IFRS 15, cost-to-cost): earned = contract value × actual
  cost ÷ budget cost; unbilled = earned − invoiced.
- Retention is due 400 days after the final invoice date (configurable).

## 7. Roles

| Group | Main rights |
|---|---|
| Sales | Leads, surveys, quotations |
| Estimator | Estimations, BOQs |
| Project Manager | First quotation approval, projects, VOs, MRs |
| Senior Manager | Second quotation approval, high-value PO approval |
| Procurement | PR, RFQ, PO |
| Storekeeper | Inventory documents, GRN |
| HR | HRMS, payroll |
| Accounts | Ledger, invoices, payments, reports |
| Admin (superuser) | Everything, configuration |

Approval rules are data (`core.ApprovalRule`), so the value bands for PR/PO
approval can be changed without code.

## 8. Reports

Trial balance, P&L, balance sheet, general ledger, customer SOA (with advance
and PDC), AR ageing (with project-wise view), AP ageing, unbilled revenue,
retention due, budget vs actual (+ run-rate forecast), project cost variance
(material / labour / subcontract), project GP & NP, monthly receivable and
profitability, inventory valuation, stock ageing, stock movement, consumption
by project, purchase analytics (spend by vendor / category / project, PO cycle
time, vendor on-time delivery), requisitions by project.

## 9. Open items to confirm with the business ("Inputs from Mr. Anoop")

The accounts sheet lists inputs still to come: voucher list, chart of accounts,
monthly receivable and profitability formats, leave salary and EOS method, visa
and trade-hours formats. The system ships with sensible defaults for each
(seeded COA, UAE gratuity method, standard report layouts) and all of them are
data or single functions that can be replaced once those inputs arrive.
