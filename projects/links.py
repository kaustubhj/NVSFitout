from core.ui import registry

for title, name in [("Project GP & NP", "proj-profit"), ("Material / labour / subcontract variance", "proj-variance"),
                    ("Project costing detail", "proj-costing")]:
    registry.link("projects", "Reports", title, name)
