import csv

from django import forms
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory, modelform_factory
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .display import column_label, format_value, is_numeric, raw_value, status_pill
from .models import Attachment, AuditLog
from .services import approval_logs, audit
from .ui import registry


def formfield_callback(field, **kwargs):
    if isinstance(field, models.DateField) and not isinstance(field, models.DateTimeField):
        kwargs["widget"] = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    if isinstance(field, models.TextField):
        kwargs["widget"] = forms.Textarea(attrs={"rows": 3})
    if isinstance(field, models.ManyToManyField):
        kwargs["widget"] = forms.SelectMultiple(attrs={"size": 6})
    return field.formfield(**kwargs)


def _screen(request, module, slug):
    try:
        screen = registry.get(module, slug)
    except KeyError:
        raise Http404("Unknown screen")
    if not screen.module.visible_to(request.user):
        raise PermissionDenied
    return screen


def _form_class(screen):
    fields = screen.form_fields or "__all__"
    return modelform_factory(screen.model, fields=fields, formfield_callback=formfield_callback)


def _scoped_formset(where):
    class Scoped(BaseInlineFormSet):
        def get_queryset(self):
            return super().get_queryset().filter(**where)

        def save_new(self, form, commit=True):
            for k, v in where.items():
                setattr(form.instance, k, v)
            return super().save_new(form, commit)
    return Scoped


def _formsets(screen, request, obj):
    sets = []
    for i, inline in enumerate(screen.inlines):
        if inline.readonly:
            continue
        fs_cls = inlineformset_factory(
            screen.model, inline.model, fields=inline.fields, fk_name=inline.fk_name,
            extra=inline.extra if obj is None or not obj.pk else 0, can_delete=True,
            formfield_callback=formfield_callback,
            formset=_scoped_formset(inline.where) if inline.where else BaseInlineFormSet, labels=inline.labels,
        )
        prefix = f"lines{i}"
        if request.method == "POST":
            fs = fs_cls(request.POST, request.FILES, instance=obj, prefix=prefix)
        else:
            fs = fs_cls(instance=obj, prefix=prefix)
        fs.inline = inline
        sets.append(fs)
    return sets


def list_view(request, module, slug):
    screen = _screen(request, module, slug)
    qs = screen.queryset(request)
    q = request.GET.get("q", "").strip()
    if q and screen.search_fields:
        cond = Q()
        for f in screen.search_fields:
            cond |= Q(**{f"{f}__icontains": q})
        qs = qs.filter(cond)
    filters = []
    for fname in screen.list_filters:
        field = screen.model._meta.get_field(fname)
        if field.choices:
            options = list(field.choices)
        elif field.is_relation:
            options = [(o.pk, str(o)) for o in field.related_model._default_manager.all()[:200]]
        elif isinstance(field, models.BooleanField):
            options = [("1", "Yes"), ("0", "No")]
        else:
            continue
        current = request.GET.get(fname, "")
        if current != "":
            if isinstance(field, models.BooleanField):
                qs = qs.filter(**{fname: current == "1"})
            else:
                qs = qs.filter(**{fname: current})
        filters.append({"name": fname, "label": column_label(screen.model, fname), "options": options,
                        "current": current})

    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{screen.slug}.csv"'
        w = csv.writer(resp)
        w.writerow([column_label(screen.model, c) for c in screen.list_display])
        for obj in qs[:10000]:
            w.writerow([raw_value(obj, c) for c in screen.list_display])
        return resp

    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    rows = []
    for obj in page:
        cells = []
        for c in screen.list_display:
            if c == "status":
                cells.append({"value": status_pill(obj), "num": False})
            else:
                cells.append({"value": format_value(raw_value(obj, c)), "num": is_numeric(obj, c)})
        rows.append({"obj": obj, "url": screen.url("detail", pk=obj.pk), "cells": cells})
    headers = [{"label": column_label(screen.model, c),
                "num": bool(page.object_list) and is_numeric(page.object_list[0], c)} for c in screen.list_display]
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "erp/list.html", {
        "screen": screen, "page": page, "rows": rows, "headers": headers, "q": q,
        "filters": filters, "querystring": params.urlencode(),
    })


def _save(request, screen, obj):
    form_cls = _form_class(screen)
    created = obj is None
    if request.method == "POST":
        form = form_cls(request.POST, request.FILES, instance=obj)
        screen.setup_form(form, request, obj)
        formsets = _formsets(screen, request, form.instance)
        if form.is_valid() and all(fs.is_valid() for fs in formsets):
            try:
                with transaction.atomic():
                    obj = form.save()
                    for fs in formsets:
                        fs.instance = obj
                        fs.save()
                    screen.after_save(request, obj, created)
                    audit(obj, "created" if created else "edited", request.user,
                          {"fields": form.changed_data})
            except ValidationError as e:
                messages.error(request, "; ".join(e.messages))
            else:
                messages.success(request, f"{screen.singular} {obj} saved.")
                if "save_add" in request.POST:
                    return redirect(screen.url("create"))
                return redirect(screen.url("detail", pk=obj.pk))
    else:
        form = form_cls(instance=obj, initial=screen.initial(request) if created else None)
        screen.setup_form(form, request, obj)
        formsets = _formsets(screen, request, obj if obj is not None else form.instance)
    return render(request, "erp/form.html", {
        "screen": screen, "form": form, "formsets": formsets, "obj": obj,
    })


def create_view(request, module, slug):
    screen = _screen(request, module, slug)
    if not screen.can_create:
        raise PermissionDenied
    return _save(request, screen, None)


def edit_view(request, module, slug, pk):
    screen = _screen(request, module, slug)
    obj = get_object_or_404(screen.model, pk=pk)
    if not screen.editable(obj):
        messages.warning(request, f"{obj} can no longer be edited in its current status.")
        return redirect(screen.url("detail", pk=pk))
    return _save(request, screen, obj)


def _detail_fields(screen, obj):
    names = screen.detail_fields
    if names is None:
        names = [f.name for f in screen.model._meta.fields if f.name not in ("id", "created_at", "updated_at")]
        names += [f.name for f in screen.model._meta.many_to_many]
    out = []
    for n in names:
        value = status_pill(obj) if n == "status" else format_value(raw_value(obj, n))
        out.append({"label": column_label(screen.model, n), "value": value,
                    "wide": isinstance(n, str) and isinstance(_get_field(screen.model, n), models.TextField)})
    return out


def _get_field(model, name):
    try:
        return model._meta.get_field(name)
    except Exception:
        return None


def _table(model_or_rows, items, columns):
    rows = []
    totals = {}
    for item in items:
        cells = []
        for c in columns:
            raw = raw_value(item, c)
            cells.append({"value": format_value(raw), "num": is_numeric(item, c)})
        rows.append({"cells": cells, "url": registry.url_for(item)})
    return rows


def detail_view(request, module, slug, pk):
    screen = _screen(request, module, slug)
    obj = get_object_or_404(screen.model, pk=pk)
    lines = []
    for inline in screen.inlines:
        fk = inline.fk_name or next(
            f.name for f in inline.model._meta.fields if f.is_relation and f.related_model == screen.model)
        items = list(inline.model._default_manager.filter(**{fk: obj}, **inline.where))
        headers = [{"label": inline.labels.get(c) or column_label(inline.model, c),
                    "num": bool(items) and is_numeric(items[0], c)} for c in inline.display]
        totals = []
        if inline.totals and items:
            for c in inline.display:
                if c in inline.totals:
                    totals.append(format_value(sum((raw_value(i, c) or 0) for i in items)))
                else:
                    totals.append("")
        lines.append({"title": inline.title, "headers": headers,
                      "rows": _table(inline.model, items, inline.display), "totals": totals})
    related = []
    for rel in screen.related:
        items = list(rel.func(obj))
        if not items:
            continue
        rmodel = type(items[0])
        related.append({
            "title": rel.title,
            "headers": [{"label": column_label(rmodel, c), "num": is_numeric(items[0], c)} for c in rel.columns],
            "rows": _table(rmodel, items, rel.columns),
        })
    ct = ContentType.objects.get_for_model(obj)
    ctx = {
        "screen": screen, "obj": obj, "fields": _detail_fields(screen, obj), "lines": lines,
        "related": related, "actions": screen.get_actions(request.user, obj),
        "editable": screen.editable(obj), "deletable": screen.deletable(obj),
        "attachments": Attachment.objects.filter(content_type=ct, object_id=obj.pk),
        "history": AuditLog.objects.filter(content_type=ct, object_id=obj.pk).select_related("user")[:30],
        "approvals": approval_logs(obj),
        "extra_panel": getattr(obj, "detail_panel", None),
    }
    if hasattr(obj, "APPROVAL_DOC_TYPE"):
        from .services import pending_rule

        ctx["pending_rule"] = pending_rule(obj)
    return render(request, "erp/detail.html", ctx)


@require_POST
def action_view(request, module, slug, pk, action):
    screen = _screen(request, module, slug)
    obj = get_object_or_404(screen.model, pk=pk)
    act = screen.get_action(action)
    if act is None or not act.visible(request.user, obj):
        messages.error(request, "That action is not available.")
        return redirect(screen.url("detail", pk=pk))
    request.action_comment = request.POST.get("comment", "")
    try:
        with transaction.atomic():
            result = act.func(request, obj)
            audit(obj, act.label, request.user, {"comment": request.action_comment} if request.action_comment else None)
    except (ValidationError, PermissionDenied) as e:
        msg = "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)
        messages.error(request, msg or "Not permitted.")
        return redirect(screen.url("detail", pk=pk))
    if isinstance(result, HttpResponse):
        return result
    if isinstance(result, models.Model):
        messages.success(request, f"{act.label}: created {result}.")
        url = registry.url_for(result)
        if url:
            return redirect(url)
    elif isinstance(result, str):
        messages.success(request, result)
    else:
        messages.success(request, f"{act.label} done.")
    return redirect(screen.url("detail", pk=pk))


def delete_view(request, module, slug, pk):
    screen = _screen(request, module, slug)
    obj = get_object_or_404(screen.model, pk=pk)
    if not screen.deletable(obj):
        messages.error(request, f"{obj} cannot be deleted in its current status.")
        return redirect(screen.url("detail", pk=pk))
    if request.method == "POST":
        label = str(obj)
        try:
            obj.delete()
        except models.ProtectedError:
            messages.error(request, f"{label} is referenced by other records and cannot be deleted.")
            return redirect(screen.url("detail", pk=pk))
        messages.success(request, f"{label} deleted.")
        return redirect(screen.url("list"))
    return render(request, "erp/confirm_delete.html", {"screen": screen, "obj": obj})


def print_view(request, module, slug, pk):
    screen = _screen(request, module, slug)
    obj = get_object_or_404(screen.model, pk=pk)
    if not screen.print_template:
        raise Http404
    from .models import Company

    return render(request, screen.print_template, {"obj": obj, "company": Company.get(), "screen": screen})


@require_POST
def attach_view(request, module, slug, pk):
    screen = _screen(request, module, slug)
    obj = get_object_or_404(screen.model, pk=pk)
    f = request.FILES.get("file")
    if f:
        Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, file=f,
            description=request.POST.get("description", "")[:200], uploaded_by=request.user,
        )
        audit(obj, f"attached {f.name}", request.user)
        messages.success(request, "File attached.")
    return redirect(screen.url("detail", pk=pk))


def module_view(request, module):
    try:
        mod = registry.modules[module]
    except KeyError:
        raise Http404
    if not mod.visible_to(request.user):
        raise PermissionDenied
    cards = []
    for screen in mod.screens.values():
        qs = screen.model._default_manager.all()
        cards.append({"screen": screen, "count": qs.count()})
    from django.urls import reverse

    sections = {}
    for section, title, url_name in mod.links:
        sections.setdefault(section, []).append((title, reverse(url_name)))
    return render(request, "erp/module.html", {"module": mod, "cards": cards, "sections": sections})


def home(request):
    from .dashboard import home_context

    return render(request, "erp/home.html", home_context(request))


def redirect_to(url):
    return HttpResponseRedirect(url)
