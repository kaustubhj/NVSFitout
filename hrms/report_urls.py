from django.urls import path

from . import reports

urlpatterns = [
    path("eos/", reports.eos, name="hr-eos"),
    path("labour-cost/", reports.labour_cost, name="hr-labour-cost"),
    path("overtime/", reports.overtime, name="hr-overtime"),
    path("trade-hours/", reports.trade_hours, name="hr-trade-hours"),
    path("documents/", reports.documents, name="hr-documents"),
    path("camps/", reports.camps, name="hr-camps"),
    path("payroll/", reports.payroll_summary, name="hr-payroll"),
]
