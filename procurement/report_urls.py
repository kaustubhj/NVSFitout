from django.urls import path

from . import reports

urlpatterns = [
    path("by-project/", reports.by_project, name="proc-by-project"),
    path("analytics/", reports.analytics, name="proc-analytics"),
    path("tracking/", reports.tracking, name="proc-tracking"),
]
