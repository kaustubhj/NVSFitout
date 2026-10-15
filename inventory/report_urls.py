from django.urls import path

from . import reports

urlpatterns = [
    path("dashboard/", reports.dashboard, name="inv-dashboard"),
    path("valuation/", reports.valuation, name="inv-valuation"),
    path("ageing/", reports.ageing, name="inv-ageing"),
    path("movement/", reports.movement, name="inv-movement"),
    path("consumption/", reports.consumption, name="inv-consumption"),
    path("availability/", reports.availability, name="inv-availability"),
    path("locations/", reports.locations, name="inv-locations"),
    path("replenishment/", reports.replenishment, name="inv-replenishment"),
]
