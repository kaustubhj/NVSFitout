# Fit-Out ERP

A complete ERP for a fit-out contractor covering **Sales, Projects, Procurement, Inventory, HRMS & Payroll
and Accounts**, built from the six process diagrams (overview + one per module). The system design,
data model and posting rules are in [`docs/DESIGN.md`](docs/DESIGN.md).

Stack: Python 3.12+, Django 5.2, SQLite (demo) or PostgreSQL (production), server-rendered UI with no build step.

## Quick start

```bash
python3 -m pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py setup_erp --demo      # roles, users, chart of accounts, masters + a full demo scenario
python3 manage.py runserver
```

Open http://127.0.0.1:8000 and sign in. All demo users share the password `Fitout@123`
(change it with `--password` or in Admin):

| User | Role(s) | Typical work |
|---|---|---|
| `admin` | superuser | everything, configuration (`/admin/`) |
| `sales` | Sales | leads, quotations |
| `estimator` | Estimator, Sales | surveys, estimations, BOQs |
| `pm` | Project Manager | 1st quotation approval, PR approval, projects, MRs |
| `sm` | Senior Manager | 2nd quotation approval, POs ≥ 50,000, VOs, stock adjustments |
| `procurement` | Procurement | PR → RFQ → PO, 1st PO approval |
| `store` | Storekeeper | GRN & inspection, issues, transfers, counts |
| `hr` | HR | employees, attendance, leave, payroll |
| `accounts` | Accounts | invoices, receipts, AP, payments, reports |

Run `python3 manage.py setup_erp` without `--demo` for a clean company with masters only.

## Where each diagram step lives

The dashboard shows the overview diagram as a clickable process map. Every box maps to a screen:

| Diagram | Steps → screens / actions |
|---|---|
| **Sales** | Lead (review → qualify) · Site survey · Cost estimation (material, labour, subcontract, other, overhead) · BOQ (*Apply overhead & margin*) · Quotation (T&C template, *Submit* → PM → SM approval, *Revise* keeps rev no., date, user, reason) · *Convert to contract* (client PO + document) · *Send sheet to store* (estimation without prices) |
| **Project** | *Create project* from contract (budget from BOQ cost split) · tasks · manpower allocation · material allocation (MRs, issues, POs on the project) · Variation order (*Submit for BOQ re-approval*, contract value and budget updated) · *Close project* (budget vs actual, GP, NP frozen) |
| **Procurement** | PR (site / replenishment / manual, value-based approval) · RFQ to several vendors · side-by-side quote comparison · *Select vendor → PO* · PO approval by value · tracking Draft → Approved → Sent → Partially / Fully received → Closed / Cancelled · GRN · 3-way match · payment · purchase return · landed cost · requisitions by project · purchase analytics |
| **Inventory** | Two warehouses with bins · products with UoM, valuation and account mapping · categories by material / trade / usage · MR · *Stock check* (shortfall raises PR) · internal request · stock issue voucher · GRN with QC · transfer · return from project · adjustment with reason & approval · physical / cycle count · replenishment · reports & dashboard |
| **HRMS** | Employees (direct / hired, several trades, documents, job descriptions) · bulk mobilization by project & job · manual attendance per project/day · OT by trade hours (normal 1.25×, Friday, public holiday 1.5×) confirmed by the fit-out team · leave & leave salary in advance · loans, fines, food, advances · payroll (cash OT kept out of salary) · WPS SIF file · EOS & air ticket · cost allocation by project · camps / rooms · visa allocation |
| **Accounts** | Chart of accounts · vouchers (JV/PV/RV/CV) with audit trail · multi-currency · AR/AP · progressive invoicing (advance, progress, final, retention release; advance recovery, retention, VAT) · receipts & PDCs · vendor invoices with 3-way match · payments & cheque printing · bank reconciliation · fixed assets & depreciation · budgets & forecast · liabilities · reports |

Reports: trial balance, P&L, balance sheet, general ledger, VAT summary, customer SOA (advance & PDC),
AR ageing (by customer and project), AP ageing, unbilled revenue (IFRS 15, cost-to-cost), retention per
project (due 400 days after final invoice), budget vs actual, monthly receivable & profitability, project
GP & NP, material / labour / subcontract variance, financial analytics, inventory valuation / ageing /
movement / consumption / availability / locations, PO tracking, purchase analytics, payroll summary, OT,
trade hours, EOS provision, document expiry, camps & visas. Every report exports to CSV and prints.

## How it is built

- `core/ui.py` — each document is declared once as a *Screen* (list columns, form, line items, workflow
  buttons, related documents); generic views render list / form / detail / print for all of them.
- `*/workflow.py` — the business actions behind the buttons.
- `accounts/services.py: post_journal()` is the only writer to the ledger; `inventory/services.py:
  move_stock()` the only writer to the stock ledger (weighted average cost). Control accounts are mapped
  in *Accounts → Control accounts*.
- Approval chains are data (*Admin → Approval rules*): document type, level, role, amount band.
- Every document keeps attachments, an audit trail and its approval log.

## Tests

```bash
python3 manage.py test core
```

The suite runs the whole demo scenario (lead → quotation revision → contract → project → MR shortfall →
PR → RFQ → PO → GRN with rejection → purchase return → landed cost → 3-way match → payment → issues →
VO → payroll → billing → PDC → depreciation → bank rec) and checks that the trial balance and balance
sheet balance, the stock ledger equals the inventory GL, and every screen and report renders. It also
covers approval permissions, PO value bands, OT rules, gratuity, 3-way-match discrepancies and stock limits.

## Production notes

- PostgreSQL: set `ERP_DB_ENGINE=postgres`, `ERP_DB_NAME`, `ERP_DB_USER`, `ERP_DB_PASSWORD`, `ERP_DB_HOST`.
- Set `ERP_SECRET_KEY`, `ERP_DEBUG=0`, `ERP_ALLOWED_HOSTS=erp.example.com`, then `python3 manage.py collectstatic`
  and serve with gunicorn / uvicorn behind nginx (uploads live in `media/`).
- Defaults to confirm with finance (the "Inputs from Mr. Anoop" list): voucher list, chart of accounts,
  monthly receivable / profitability layouts, leave salary method ((basic + housing) ÷ 30 × days), EOS method
  (UAE gratuity on basic), visa and trade-hours formats. All are seed data or a single function.
