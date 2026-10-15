"""Type-ahead customer box: pick an existing customer from the suggestions or type a new name."""
from django import forms
from django.utils.html import format_html, format_html_join

from .models import Customer


class CustomerInput(forms.TextInput):
    def __init__(self, attrs=None):
        super().__init__({"autocomplete": "off", "placeholder": "Type to search or enter a new customer", **(attrs or {})})

    def render(self, name, value, attrs=None, renderer=None):
        list_id = f"{(attrs or {}).get('id') or name}_list"
        self.attrs["list"] = list_id
        options = format_html_join("", '<option value="{}">{}</option>',
                                   ((c.name, c.code) for c in Customer.objects.filter(active=True)))
        return format_html('{}<datalist id="{}">{}</datalist>', super().render(name, value, attrs, renderer),
                           list_id, options)


class CustomerField(forms.Field):
    """Cleans to an existing Customer (matched by name or code) or None; an unknown name is kept in
    ``new_name`` so the form can create the customer only once the whole form is valid."""
    widget = CustomerInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.new_name = ""

    def prepare_value(self, value):
        if isinstance(value, Customer):
            return value.name
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            customer = Customer.objects.filter(pk=value).first()
            return customer.name if customer else value
        return value

    def to_python(self, value):
        self.new_name = ""
        text = " ".join((value or "").split())
        if not text:
            return None
        customer = (Customer.objects.filter(name__iexact=text).first()
                    or Customer.objects.filter(code__iexact=text).first())
        if customer is None:
            self.new_name = text
        return customer


def use_customer_box(form, contact=lambda instance: {}):
    """Swap a form's customer dropdown for the type-ahead box; new names become customers on save."""
    if "customer" not in form.fields:
        return
    old = form.fields["customer"]
    field = form.fields["customer"] = CustomerField(
        required=old.required, label=old.label,
        help_text="Pick from the list or type a new name. Left blank, it is created from Company on qualifying.")
    save = form.save

    def save_with_customer(commit=True):
        if field.new_name and form.instance.customer_id is None:
            form.instance.customer = Customer.create_named(field.new_name, **contact(form.instance))
        return save(commit)

    form.save = save_with_customer
