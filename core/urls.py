from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("m/<str:module>/", views.module_view, name="erp-module"),
    path("m/<str:module>/<str:slug>/", views.list_view, name="erp-list"),
    path("m/<str:module>/<str:slug>/new/", views.create_view, name="erp-create"),
    path("m/<str:module>/<str:slug>/<int:pk>/", views.detail_view, name="erp-detail"),
    path("m/<str:module>/<str:slug>/<int:pk>/edit/", views.edit_view, name="erp-edit"),
    path("m/<str:module>/<str:slug>/<int:pk>/delete/", views.delete_view, name="erp-delete"),
    path("m/<str:module>/<str:slug>/<int:pk>/print/", views.print_view, name="erp-print"),
    path("m/<str:module>/<str:slug>/<int:pk>/attach/", views.attach_view, name="erp-attach"),
    path("m/<str:module>/<str:slug>/<int:pk>/do/<str:action>/", views.action_view, name="erp-action"),
]
