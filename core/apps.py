from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"

    def ready(self):
        from .ui import registry

        registry.module("sales", "Sales", "◆", 1, groups=("Sales", "Estimator", "Project Manager", "Senior Manager"))
        registry.module("projects", "Projects", "▣", 2, groups=("Project Manager", "Senior Manager", "Accounts", "Storekeeper"))
        registry.module("procurement", "Procurement", "⇄", 3, groups=("Procurement", "Project Manager", "Senior Manager", "Storekeeper", "Accounts"))
        registry.module("inventory", "Inventory", "▤", 4, groups=("Storekeeper", "Procurement", "Project Manager", "Senior Manager"))
        registry.module("hrms", "HRMS & Payroll", "☺", 5, groups=("HR", "Project Manager", "Senior Manager", "Accounts"))
        registry.module("accounts", "Accounts", "∑", 6, groups=("Accounts", "Senior Manager"))
        from importlib import import_module

        for app in ("sales", "projects", "procurement", "inventory", "hrms", "accounts"):
            import_module(f"{app}.ui")
            try:
                import_module(f"{app}.links")
            except ModuleNotFoundError as e:
                if e.name != f"{app}.links":
                    raise
