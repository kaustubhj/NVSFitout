from core.ui import registry

for title, name in [("Payroll summary", "hr-payroll"), ("Cost allocation by project", "hr-labour-cost"),
                    ("Overtime summary", "hr-overtime"), ("Trade hours", "hr-trade-hours"),
                    ("EOS & air ticket provision", "hr-eos"), ("Document expiry", "hr-documents"),
                    ("Camps & visas", "hr-camps")]:
    registry.link("hrms", "Reports", title, name)
