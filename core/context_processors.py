from .models import Company
from .ui import registry


def erp(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    path = request.path
    menu = []
    for mod in registry.ordered():
        if mod.visible_to(request.user):
            menu.append({"module": mod, "active": path.startswith(f"/m/{mod.key}/") or path.startswith(f"/{mod.key}/")})
    return {"menu": menu, "company": Company.get()}
