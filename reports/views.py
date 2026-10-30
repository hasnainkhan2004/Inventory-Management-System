from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from . import services


PAGE_SIZE = 20


def _report_page(request, template_name, context, key):
    page_obj = Paginator(context[key], PAGE_SIZE).get_page(
        request.GET.get('page'),
    )
    context[key] = page_obj.object_list
    context['page_obj'] = page_obj
    pagination_parameters = request.GET.copy()
    pagination_parameters.pop('page', None)
    context['pagination_query'] = pagination_parameters.urlencode()
    return render(request, template_name, context)


def _export_response(request, report_name, headers, rows):
    content = services.csv_content(headers, rows)
    filename = f'{report_name}_{timezone.localdate():%Y-%m-%d}.csv'
    response = HttpResponse(
        content.encode('utf-8'),
        content_type='text/csv; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required(login_url='login')
def hub(request):
    return render(request, 'reports/hub.html')


@login_required(login_url='login')
def stock_valuation(request):
    context = services.get_stock_valuation(request.GET)
    if request.GET.get('export') == 'csv':
        headers, rows = services.valuation_csv_rows(request.GET)
        return _export_response(request, 'stock_valuation', headers, rows)
    return _report_page(
        request,
        'reports/stock_valuation.html',
        context,
        'products',
    )


@login_required(login_url='login')
def stock_movement_report(request):
    context = services.get_stock_movement_report(request.GET)
    if request.GET.get('export') == 'csv':
        headers, rows = services.movement_csv_rows(request.GET)
        return _export_response(request, 'stock_movement_report', headers, rows)
    return _report_page(
        request,
        'reports/stock_movement_report.html',
        context,
        'movements',
    )


@login_required(login_url='login')
def low_stock_report(request):
    context = services.get_low_stock_report(request.GET)
    if request.GET.get('export') == 'csv':
        headers, rows = services.low_stock_csv_rows(request.GET)
        return _export_response(request, 'low_stock_report', headers, rows)
    return _report_page(
        request,
        'reports/low_stock_report.html',
        context,
        'products',
    )


@login_required(login_url='login')
def supplier_stock_report(request):
    report = services.get_supplier_stock_report()
    if request.GET.get('export') == 'csv':
        headers, rows = services.supplier_stock_csv_rows()
        return _export_response(request, 'supplier_stock_report', headers, rows)
    return _report_page(
        request,
        'reports/supplier_stock_report.html',
        report,
        'suppliers',
    )
