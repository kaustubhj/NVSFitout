from django.urls import path

from . import reports

urlpatterns = [
    path("profit/", reports.portfolio, name="proj-profit"),
    path("variance/", reports.variance, name="proj-variance"),
    path("costing/", reports.costing, name="proj-costing"),
]
