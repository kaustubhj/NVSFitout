from core.ui import registry

for title, name in [("Bank reconciliation", "acc-bank-rec"), ("Financial analytics", "acc-analytics")]:
    registry.link("accounts", "Banking & analytics", title, name)
for title, name in [("Trial balance", "acc-tb"), ("Profit & loss", "acc-pl"), ("Balance sheet", "acc-bs"),
                    ("General ledger", "acc-ledger"), ("VAT summary", "acc-vat")]:
    registry.link("accounts", "Financial reports", title, name)
for title, name in [("Customer SOA (advance & PDC)", "acc-soa"), ("Receivables ageing (project-wise)", "acc-ar-ageing"),
                    ("Payables ageing", "acc-ap-ageing"), ("Unbilled revenue (IFRS 15)", "acc-unbilled"),
                    ("Retention per project", "acc-retention"), ("Monthly receivable & profitability", "acc-monthly")]:
    registry.link("accounts", "Receivables & project billing", title, name)
for title, name in [("Budget vs actual & forecast", "acc-budget"), ("Project GP & NP", "proj-profit"),
                    ("Material / labour / subcontract variance", "proj-variance")]:
    registry.link("accounts", "Planning & project profitability", title, name)
