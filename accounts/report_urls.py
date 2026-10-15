from django.urls import path

from . import reports

urlpatterns = [
    path("trial-balance/", reports.trial_balance, name="acc-tb"),
    path("profit-loss/", reports.profit_loss, name="acc-pl"),
    path("balance-sheet/", reports.balance_sheet, name="acc-bs"),
    path("ledger/", reports.ledger, name="acc-ledger"),
    path("soa/", reports.soa, name="acc-soa"),
    path("ar-ageing/", reports.ar_ageing, name="acc-ar-ageing"),
    path("ap-ageing/", reports.ap_ageing, name="acc-ap-ageing"),
    path("unbilled/", reports.unbilled, name="acc-unbilled"),
    path("retention/", reports.retention, name="acc-retention"),
    path("budget/", reports.budget_vs_actual, name="acc-budget"),
    path("monthly/", reports.monthly, name="acc-monthly"),
    path("vat/", reports.vat, name="acc-vat"),
    path("analytics/", reports.analytics, name="acc-analytics"),
    path("bank-reconciliation/", reports.bank_reconciliation, name="acc-bank-rec"),
]
