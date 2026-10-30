import csv
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Greatest, TruncDate
from django.utils import timezone

from inventory.models import Category, Product, StockMovement, Supplier


MONEY_FIELD = DecimalField(max_digits=18, decimal_places=2)


def _positive_id(value, model):
    if not value or not str(value).isdigit():
        return None
    return int(value) if model.objects.filter(pk=value).exists() else None


def _money_sum(field):
    return Coalesce(Sum(field), Value(Decimal('0.00')), output_field=MONEY_FIELD)


def _valuation_queryset(params):
    products = Product.objects.select_related('category', 'supplier').annotate(
        cost_value=ExpressionWrapper(
            F('quantity') * F('cost_price'),
            output_field=MONEY_FIELD,
        ),
        retail_value=ExpressionWrapper(
            F('quantity') * F('selling_price'),
            output_field=MONEY_FIELD,
        ),
        potential_profit=ExpressionWrapper(
            F('quantity') * (F('selling_price') - F('cost_price')),
            output_field=MONEY_FIELD,
        ),
    )
    category_id = _positive_id(params.get('category'), Category)
    supplier_id = _positive_id(params.get('supplier'), Supplier)
    status = params.get('status', '')
    query = params.get('q', '').strip()
    if category_id:
        products = products.filter(category_id=category_id)
    if supplier_id:
        products = products.filter(supplier_id=supplier_id)
    if status == 'active':
        products = products.filter(is_active=True)
    elif status == 'inactive':
        products = products.filter(is_active=False)
    else:
        status = ''
    if query:
        products = products.filter(Q(name__icontains=query) | Q(sku__icontains=query))
    return products.order_by('name'), {
        'category_filter': str(category_id or ''),
        'supplier_filter': str(supplier_id or ''),
        'status_filter': status,
        'query': query,
    }


def get_stock_valuation(params=None):
    params = params or {}
    products, filters = _valuation_queryset(params)
    totals = products.aggregate(
        total_cost_value=_money_sum('cost_value'),
        total_retail_value=_money_sum('retail_value'),
        total_potential_profit=_money_sum('potential_profit'),
        total_units=Coalesce(Sum('quantity'), Value(0), output_field=IntegerField()),
    )
    categories = (
        products.values('category__name')
        .annotate(cost_value=_money_sum('cost_value'))
        .order_by('category__name')
    )
    chart_data = [
        {
            'label': row['category__name'] or 'Uncategorized',
            'value': str(row['cost_value']),
        }
        for row in categories
    ]
    return {
        'products': products,
        'totals': totals,
        'chart_data': chart_data,
        'filters': filters,
        'categories': Category.objects.order_by('name'),
        'suppliers': Supplier.objects.order_by('name'),
    }


def _parse_report_dates(params):
    today = timezone.localdate()
    default_start = today - timedelta(days=29)
    raw_start = params.get('start_date', '')
    raw_end = params.get('end_date', '')
    errors = []
    try:
        start = date.fromisoformat(raw_start) if raw_start else default_start
    except ValueError:
        start = default_start
        errors.append('Start date is invalid; showing the last 30 days instead.')
    try:
        end = date.fromisoformat(raw_end) if raw_end else today
    except ValueError:
        end = today
        errors.append('End date is invalid; showing the last 30 days instead.')
    if errors:
        start, end = default_start, today
    elif start > end:
        errors.append('Start date must be on or before the end date.')
    return start, end, errors


def _movement_queryset(params, start, end):
    movements = StockMovement.objects.select_related(
        'product',
        'product__category',
        'product__supplier',
        'created_by',
    )
    if start <= end:
        movements = movements.filter(
            created_at__date__gte=start,
            created_at__date__lte=end,
        )
    else:
        movements = movements.none()

    product_id = _positive_id(params.get('product'), Product)
    category_id = _positive_id(params.get('category'), Category)
    user_id = _positive_id(params.get('user'), get_user_model())
    movement_type = params.get('movement_type', '')
    reason = params.get('reason', '')
    if product_id:
        movements = movements.filter(product_id=product_id)
    if category_id:
        movements = movements.filter(product__category_id=category_id)
    if movement_type in StockMovement.MovementType.values:
        movements = movements.filter(movement_type=movement_type)
    else:
        movement_type = ''
    valid_reasons = {reason for _, reason in StockMovement.REASON_CHOICES}
    if reason in valid_reasons:
        movements = movements.filter(reason=reason)
    else:
        reason = ''
    if user_id:
        movements = movements.filter(created_by_id=user_id)
    return movements.order_by('-created_at', '-pk'), {
        'product_filter': str(product_id or ''),
        'category_filter': str(category_id or ''),
        'movement_type_filter': movement_type,
        'reason_filter': reason,
        'user_filter': str(user_id or ''),
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
    }


def get_stock_movement_report(params=None):
    params = params or {}
    start, end, errors = _parse_report_dates(params)
    movements, filters = _movement_queryset(params, start, end)
    filters['date_error'] = ' '.join(errors)
    totals = movements.aggregate(
        total_in=Coalesce(
            Sum('quantity', filter=Q(movement_type=StockMovement.MovementType.IN)),
            Value(0),
            output_field=IntegerField(),
        ),
        total_out=Coalesce(
            Sum('quantity', filter=Q(movement_type=StockMovement.MovementType.OUT)),
            Value(0),
            output_field=IntegerField(),
        ),
        net_change=Coalesce(
            Sum('quantity_change'),
            Value(0),
            output_field=IntegerField(),
        ),
        movement_count=Count('pk'),
    )
    daily = (
        movements.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            total_in=Coalesce(
                Sum('quantity', filter=Q(movement_type=StockMovement.MovementType.IN)),
                Value(0),
                output_field=IntegerField(),
            ),
            total_out=Coalesce(
                Sum('quantity', filter=Q(movement_type=StockMovement.MovementType.OUT)),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .order_by('day')
    )
    daily_values = {row['day']: row for row in daily}
    chart_data = []
    if start <= end:
        day = start
        while day <= end:
            row = daily_values.get(day, {})
            chart_data.append({
                'label': day.isoformat(),
                'in': row.get('total_in', 0),
                'out': row.get('total_out', 0),
            })
            day += timedelta(days=1)

    top_products = (
        movements.filter(movement_type=StockMovement.MovementType.OUT)
        .values('product_id', 'product__name', 'product__sku')
        .annotate(quantity_out=Sum('quantity'))
        .order_by('-quantity_out', 'product__name')[:5]
    )
    return {
        'movements': movements,
        'totals': totals,
        'chart_data': chart_data,
        'top_products': top_products,
        'filters': filters,
        'products': Product.objects.order_by('name'),
        'categories': Category.objects.order_by('name'),
        'users': get_user_model().objects.order_by('username'),
        'movement_types': StockMovement.MovementType.choices,
        'reasons': StockMovement.REASON_CHOICES,
        'quick_periods': _quick_periods(),
    }


def _quick_periods():
    today = timezone.localdate()
    month_start = today.replace(day=1)
    return {
        'today': (today, today),
        '7_days': (today - timedelta(days=6), today),
        '30_days': (today - timedelta(days=29), today),
        'this_month': (month_start, today),
    }


def get_low_stock_report(params=None):
    params = params or {}
    products = Product.objects.select_related('category', 'supplier').filter(
        is_active=True,
        quantity__lte=F('low_stock_threshold'),
    )
    category_id = _positive_id(params.get('category'), Category)
    supplier_id = _positive_id(params.get('supplier'), Supplier)
    if category_id:
        products = products.filter(category_id=category_id)
    if supplier_id:
        products = products.filter(supplier_id=supplier_id)
    products = products.annotate(
        suggested_reorder=Greatest(
            ExpressionWrapper(
                F('low_stock_threshold') * 2 - F('quantity'),
                output_field=IntegerField(),
            ),
            Value(1),
        ),
    ).order_by('quantity', 'name')
    totals = products.aggregate(
        product_count=Count('pk'),
        out_of_stock_count=Count('pk', filter=Q(quantity=0)),
        suggested_reorder_total=Coalesce(
            Sum('suggested_reorder'),
            Value(0),
            output_field=IntegerField(),
        ),
    )
    return {
        'products': products,
        'totals': totals,
        'filters': {
            'category_filter': str(category_id or ''),
            'supplier_filter': str(supplier_id or ''),
        },
        'categories': Category.objects.order_by('name'),
        'suppliers': Supplier.objects.order_by('name'),
    }


def get_supplier_stock_report():
    suppliers = Supplier.objects.annotate(
        product_count=Count('products', distinct=True),
        total_units=Coalesce(
            Sum('products__quantity'),
            Value(0),
            output_field=IntegerField(),
        ),
        total_cost_value=Coalesce(
            Sum(
                ExpressionWrapper(
                    F('products__quantity') * F('products__cost_price'),
                    output_field=MONEY_FIELD,
                ),
            ),
            Value(Decimal('0.00')),
            output_field=MONEY_FIELD,
        ),
        low_stock_count=Count(
            'products',
            filter=Q(
                products__quantity__lte=F('products__low_stock_threshold'),
            ),
            distinct=True,
        ),
    ).order_by('name')
    totals = Supplier.objects.aggregate(
        supplier_count=Count('pk'),
    )
    product_totals = Product.objects.filter(supplier__isnull=False).aggregate(
        product_count=Count('pk'),
        total_units=Coalesce(Sum('quantity'), Value(0), output_field=IntegerField()),
        total_cost_value=Coalesce(
            Sum(
                ExpressionWrapper(
                    F('quantity') * F('cost_price'),
                    output_field=MONEY_FIELD,
                ),
            ),
            Value(Decimal('0.00')),
            output_field=MONEY_FIELD,
        ),
        low_stock_count=Count(
            'pk',
            filter=Q(quantity__lte=F('low_stock_threshold')),
        ),
    )
    return {
        'suppliers': suppliers,
        'totals': {**totals, **product_totals},
    }


def csv_safe(value):
    text = '' if value is None else str(value)
    if isinstance(value, str) and text.startswith(('=', '+', '-', '@')):
        return f"'{text}"
    return text


def csv_content(headers, rows):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([csv_safe(value) for value in headers])
    for row in rows:
        writer.writerow([csv_safe(value) for value in row])
    return '\ufeff' + output.getvalue()


def valuation_csv_rows(params=None):
    report = get_stock_valuation(params)
    rows = (
        (
            product.name,
            product.sku,
            product.category.name if product.category else '',
            product.supplier.name if product.supplier else '',
            product.quantity,
            product.cost_price,
            product.selling_price,
            product.cost_value,
            product.retail_value,
            product.potential_profit,
        )
        for product in report['products']
    )
    return (
        ('Product', 'SKU', 'Category', 'Supplier', 'Quantity', 'Cost price',
         'Selling price', 'Stock cost value', 'Stock retail value', 'Potential profit'),
        rows,
    )


def movement_csv_rows(params=None):
    report = get_stock_movement_report(params)
    rows = (
        (
            movement.created_at.isoformat(),
            movement.product.name,
            movement.product.sku,
            movement.movement_type,
            movement.quantity_change,
            movement.quantity_before,
            movement.quantity_after,
            movement.reason,
            movement.created_by.get_username(),
            movement.note,
            movement.reference,
        )
        for movement in report['movements']
    )
    return (
        ('Date', 'Product', 'SKU', 'Type', 'Change', 'Before', 'After',
         'Reason', 'User', 'Note', 'Reference'),
        rows,
    )


def low_stock_csv_rows(params=None):
    report = get_low_stock_report(params)
    rows = (
        (
            product.name,
            product.sku,
            product.supplier.name if product.supplier else '',
            product.supplier.phone if product.supplier else '',
            product.quantity,
            product.low_stock_threshold,
            product.suggested_reorder,
            'Out of stock' if product.quantity == 0 else 'Low',
        )
        for product in report['products']
    )
    return (
        ('Product', 'SKU', 'Supplier', 'Supplier phone', 'Current quantity',
         'Threshold', 'Suggested reorder quantity', 'Status'),
        rows,
    )


def supplier_stock_csv_rows():
    rows = (
        (
            supplier.name,
            supplier.product_count,
            supplier.total_units,
            supplier.total_cost_value,
            supplier.low_stock_count,
        )
        for supplier in get_supplier_stock_report()['suppliers']
    )
    return (
        ('Supplier', 'Product count', 'Total units', 'Total cost value', 'Low stock items'),
        rows,
    )
