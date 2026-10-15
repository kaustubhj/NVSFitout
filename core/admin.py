from django.apps import apps
from django.contrib import admin

# Everything is reachable in Django admin as a fallback for configuration and data fixes.
for app in ("core", "sales", "projects", "inventory", "procurement", "hrms", "accounts"):
    for model in apps.get_app_config(app).get_models():
        try:
            admin.site.register(model)
        except admin.sites.AlreadyRegistered:
            pass
