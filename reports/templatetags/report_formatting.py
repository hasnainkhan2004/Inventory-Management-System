from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def currency(value):
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal('0.00')
    return f'Rs {amount:,.2f}'
