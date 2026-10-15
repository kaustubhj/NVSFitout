from core.ui import registry

for title, name in [("PO tracking", "proc-tracking"), ("Requisitions by project", "proc-by-project"),
                    ("Purchase analytics", "proc-analytics")]:
    registry.link("procurement", "Reports", title, name)
