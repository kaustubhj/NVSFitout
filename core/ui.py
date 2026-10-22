"""A small declarative UI layer: every business document is described once as a
Screen (list columns, form fields, line items, workflow actions, related
documents) and rendered by the generic views in core.views."""
from collections import OrderedDict

from django.urls import reverse


class Action:
    def __init__(self, name, label, func, when=None, groups=None, confirm=None,
                 style="primary", prompt=None, check=None):
        self.name = name
        self.label = label
        self.func = func
        self.when = when or (lambda obj: True)
        self.groups = groups or []
        self.confirm = confirm
        self.style = style
        self.prompt = prompt
        self.check = check

    def visible(self, user, obj):
        if not self.when(obj):
            return False
        if self.check is not None and not self.check(user, obj):
            return False
        if not self.groups or user.is_superuser:
            return True
        return user.groups.filter(name__in=self.groups).exists()


class Inline:
    def __init__(self, model, fields, fk_name=None, extra=1, title=None, totals=(),
                 display=None, readonly=False, where=None):
        self.model = model
        self.fields = fields
        self.fk_name = fk_name
        self.extra = extra
        self.title = title or model._meta.verbose_name_plural.title()
        self.totals = totals
        # columns shown on the detail page (defaults to the form fields)
        self.display = display or fields
        # read-only inlines are shown on the detail page but not edited in the form
        self.readonly = readonly
        # fixed field values for this table, e.g. {"category": "labour"}: only matching lines are shown,
        # and new lines get these values, so one line model can be split into several sections
        self.where = where or {}


class Related:
    """A list of linked documents shown on a detail page."""

    def __init__(self, title, func, columns):
        self.title = title
        self.func = func
        self.columns = columns


class Screen:
    model = None
    slug = None
    title = None
    list_display = ("number", "date", "status")
    search_fields = ("number",)
    list_filters = ("status",)
    form_fields = None
    detail_fields = None
    inlines = ()
    actions = ()
    related = ()
    can_create = True
    groups = ()
    print_template = None
    ordering = None
    help_text = ""

    def __init__(self, module):
        self.module = module
        from django.utils.text import capfirst

        self.title = self.title or capfirst(self.model._meta.verbose_name_plural)
        self.singular = capfirst(self.model._meta.verbose_name)

    # hooks -------------------------------------------------------------
    def queryset(self, request):
        qs = self.model._default_manager.all()
        if self.ordering:
            qs = qs.order_by(*self.ordering)
        return qs

    def editable(self, obj):
        status = getattr(obj, "status", None)
        return status in (None, "draft")

    def deletable(self, obj):
        return self.editable(obj)

    def initial(self, request):
        return {k: v for k, v in request.GET.items()}

    def setup_form(self, form, request, obj):
        pass

    def after_save(self, request, obj, created):
        recalc = getattr(obj, "recalc", None)
        if callable(recalc):
            recalc()

    def get_actions(self, user, obj):
        return [a for a in self.actions if a.visible(user, obj)]

    def get_action(self, name):
        for a in self.actions:
            if a.name == name:
                return a
        return None

    # urls ---------------------------------------------------------------
    def url(self, view="list", pk=None, **extra):
        kwargs = {"module": self.module.key, "slug": self.slug}
        if pk is not None:
            kwargs["pk"] = pk
        kwargs.update(extra)
        return reverse(f"erp-{view}", kwargs=kwargs)


class Module:
    def __init__(self, key, title, icon, order, groups=()):
        self.key = key
        self.title = title
        self.icon = icon
        self.order = order
        self.groups = groups
        self.screens = OrderedDict()
        self.links = []  # (section, title, url name)

    def visible_to(self, user):
        if user.is_superuser or not self.groups:
            return True
        return user.groups.filter(name__in=self.groups).exists()


class Registry:
    def __init__(self):
        self.modules = {}
        self._by_model = {}

    def module(self, key, title, icon="", order=99, groups=()):
        if key not in self.modules:
            self.modules[key] = Module(key, title, icon, order, groups)
        return self.modules[key]

    def register(self, module_key, screen_cls):
        module = self.modules[module_key]
        screen = screen_cls(module)
        module.screens[screen.slug] = screen
        self._by_model[screen.model] = screen
        return screen_cls

    def link(self, module_key, section, title, url_name):
        self.modules[module_key].links.append((section, title, url_name))

    def get(self, module_key, slug):
        return self.modules[module_key].screens[slug]

    def for_model(self, model):
        return self._by_model.get(model)

    def ordered(self):
        return sorted(self.modules.values(), key=lambda m: m.order)

    def url_for(self, obj):
        screen = self.for_model(type(obj))
        if screen is None or obj.pk is None:
            return None
        return screen.url("detail", pk=obj.pk)


registry = Registry()


def register(module_key):
    def wrap(cls):
        registry.register(module_key, cls)
        return cls

    return wrap
