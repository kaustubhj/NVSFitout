from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("reports/inventory/", include("inventory.report_urls")),
    path("reports/procurement/", include("procurement.report_urls")),
    path("reports/projects/", include("projects.report_urls")),
    path("reports/hrms/", include("hrms.report_urls")),
    path("reports/accounts/", include("accounts.report_urls")),
    path("", include("core.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
