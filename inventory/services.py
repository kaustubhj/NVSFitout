"""The only entry point that writes to the stock ledger (weighted average cost)."""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from core.models import ZERO
from core.services import q2

from .models import StockBalance, StockMove


def move_stock(product, warehouse, qty, unit_cost=None, *, date, move_type, source=None, project=None, bin=None,
               reference=""):
    """qty > 0 receives at unit_cost; qty < 0 issues at current average cost.

    Returns the StockMove. Value is signed like qty.
    """
    qty = Decimal(qty)
    if qty == 0:
        return None
    if not product.is_stock:
        raise ValidationError(f"{product} is not a stock item.")
    bal, _ = StockBalance.objects.select_for_update().get_or_create(product=product, warehouse=warehouse)
    if qty < 0:
        if bal.qty + qty < 0:
            raise ValidationError(
                f"Not enough stock of {product.code} in {warehouse.code}: available {bal.qty:g}, needed {-qty:g}.")
        cost = (bal.value / bal.qty) if bal.qty else (unit_cost or product.standard_cost)
        value = q2(cost * qty)
        if bal.qty + qty == 0:
            value = -bal.value  # clear residual rounding
    else:
        cost = unit_cost if unit_cost is not None else product.avg_cost(warehouse)
        value = q2(cost * qty)
    bal.qty += qty
    bal.value += value
    bal.save()
    move = StockMove(product=product, warehouse=warehouse, qty=qty, unit_cost=(value / qty) if qty else ZERO,
                     value=value, date=date, move_type=move_type, project=project, bin=bin, reference=reference)
    if source is not None:
        move.content_type = ContentType.objects.get_for_model(source)
        move.object_id = source.pk
        move.reference = move.reference or str(getattr(source, "number", source))
    move.save()
    return move


def revalue_stock(product, warehouse, amount, *, date, source=None, reference=""):
    """Add value without quantity (landed cost)."""
    bal, _ = StockBalance.objects.select_for_update().get_or_create(product=product, warehouse=warehouse)
    bal.value += amount
    bal.save()
    move = StockMove(product=product, warehouse=warehouse, qty=ZERO, unit_cost=ZERO, value=amount, date=date,
                     move_type="landed_cost", reference=reference)
    if source is not None:
        move.content_type = ContentType.objects.get_for_model(source)
        move.object_id = source.pk
    move.save()
    return move


def stock_account(product):
    from accounts.services import ctl

    return product.stock_account or ctl().require("inventory")


def expense_account(product):
    from accounts.services import ctl

    if product.expense_account:
        return product.expense_account
    if not product.is_stock:
        return ctl().require("subcontract_cost")
    return ctl().require("material_cost")
