from core.ui import registry

for title, name in [("Inventory dashboard", "inv-dashboard"), ("Replenishment (reorder → PR)", "inv-replenishment")]:
    registry.link("inventory", "Dashboards & tools", title, name)
for title, name in [("Valuation", "inv-valuation"), ("Stock ageing", "inv-ageing"), ("Movement", "inv-movement"),
                    ("Consumption by project", "inv-consumption"), ("Availability & reservations", "inv-availability"),
                    ("Warehouse & bin locations", "inv-locations")]:
    registry.link("inventory", "Reports", title, name)
