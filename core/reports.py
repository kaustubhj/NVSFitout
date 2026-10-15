"""Helpers for tabular report pages."""
import csv
from decimal import Decimal

from django import forms
from django.http import HttpResponse
from django.shortcuts import render

from .display import format_value


class Table:
    def __init__(self, title, headers, rows, totals=None, links=None):
        self.title = title
        self.headers = headers
        self.rows = rows
        self.totals = totals
        self.links = links or []


def total_row(rows, numeric_cols, label="Total"):
    if not rows:
        return None
    out = [""] * len(rows[0])
    out[0] = label
    for i in numeric_cols:
        out[i] = sum((Decimal(r[i] or 0) for r in rows), Decimal("0"))
    return out


class DateRangeForm(forms.Form):
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}), label="From")
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}), label="To")


def render_report(request, title, tables, form=None, kpis=None, note=None, back=None):
    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{title.lower().replace(" ", "_")}.csv"'
        w = csv.writer(resp)
        for t in tables:
            w.writerow([t.title])
            w.writerow(t.headers)
            for r in t.rows:
                w.writerow([str(c) if c is not None else "" for c in r])
            if t.totals:
                w.writerow([str(c) for c in t.totals])
            w.writerow([])
        return resp
    rendered = []
    for t in tables:
        rows = []
        for i, r in enumerate(t.rows):
            rows.append({"cells": [{"v": format_value(c), "num": isinstance(c, (int, float, Decimal)) and not isinstance(c, bool)} for c in r],
                         "url": t.links[i] if i < len(t.links) else None})
        totals = None
        if t.totals:
            totals = [{"v": format_value(c) if c != "" else "", "num": isinstance(c, (int, float, Decimal))} for c in t.totals]
        rendered.append({"title": t.title, "headers": t.headers, "rows": rows, "totals": totals})
    params = request.GET.copy()
    params["export"] = "csv"
    return render(request, "erp/report.html", {
        "title": title, "tables": rendered, "form": form, "kpis": kpis or [], "note": note,
        "csv_query": params.urlencode(), "back": back,
    })
