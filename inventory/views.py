from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum, F, Q
from django.db.models.deletion import ProtectedError
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from .models import Category, Product, StockMovement, Supplier
from .forms import (
    CategoryForm,
    ProductForm,
    SignUpForm,
    StockMovementForm,
    SupplierForm,
)
from .services import StockMovementError, apply_stock_movement


def sign_up(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    next_url = request.POST.get('next') or request.GET.get('next', '')
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            if url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('dashboard')
    else:
        form = SignUpForm()

    return render(request, 'inventory/signup.html', {'form': form, 'next': next_url})


@login_required(login_url='login')
def dashboard(request):
    total_products = Product.objects.count()
    total_stock_value = Product.objects.aggregate(
        total=Sum(F('selling_price') * F('quantity'))
    )['total'] or 0
    low_stock_products = Product.objects.select_related('supplier').filter(
        quantity__lt=F('low_stock_threshold'),
    )
    category_stock = (
        Product.objects.filter(quantity__gt=0)
        .values('category__name')
        .annotate(quantity=Sum('quantity'))
        .order_by('category__name')
    )
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    weekly_movements = StockMovement.objects.filter(created_at__date__gte=week_start)
    weekly_totals = weekly_movements.aggregate(
        stock_in=Sum('quantity', filter=Q(movement_type=StockMovement.MovementType.IN)),
        stock_out=Sum('quantity', filter=Q(movement_type=StockMovement.MovementType.OUT)),
    )
    top_suppliers = (
        Supplier.objects.filter(products__isnull=False)
        .annotate(
            product_count=Count('products'),
            stock_value=Sum(
                F('products__selling_price') * F('products__quantity'),
            ),
        )
        .order_by('-stock_value', 'name')[:5]
    )

    context = {
        'total_products': total_products,
        'total_stock_value': total_stock_value,
        'low_stock_products': low_stock_products,
        'low_stock_count': low_stock_products.count(),
        'stock_by_category': [
            {
                'label': row['category__name'] or 'Uncategorized',
                'quantity': row['quantity'],
            }
            for row in category_stock
        ],
        'stock_in_this_week': weekly_totals['stock_in'] or 0,
        'stock_out_this_week': weekly_totals['stock_out'] or 0,
        'weekly_stock_summary': (
            f"+{weekly_totals['stock_in'] or 0} / "
            f"-{weekly_totals['stock_out'] or 0}"
        ),
        'recent_movements': StockMovement.objects.select_related(
            'product',
            'created_by',
        )[:5],
        'top_suppliers': top_suppliers,
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required(login_url='login')
def product_list(request):
    query = request.GET.get('q', '')
    category_filter = request.GET.get('category', '')
    status_filter = request.GET.get('status', '')
    supplier_filter = request.GET.get('supplier', '')
    products = Product.objects.select_related(
        'category', 'unit', 'supplier',
    ).order_by('-created_at')
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(sku__icontains=query),
        )
    if category_filter.isdigit():
        products = products.filter(category_id=category_filter)
    else:
        category_filter = ''
    if supplier_filter.isdigit():
        products = products.filter(supplier_id=supplier_filter)
    else:
        supplier_filter = ''
    if status_filter == 'active':
        products = products.filter(is_active=True)
    elif status_filter == 'inactive':
        products = products.filter(is_active=False)
    else:
        status_filter = ''

    page_obj = Paginator(products, 20).get_page(request.GET.get('page'))
    pagination_parameters = request.GET.copy()
    pagination_parameters.pop('page', None)
    return render(request, 'inventory/product_list.html', {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'query': query,
        'categories': Category.objects.order_by('name'),
        'suppliers': Supplier.objects.order_by('name'),
        'category_filter': category_filter,
        'supplier_filter': supplier_filter,
        'status_filter': status_filter,
        'pagination_query': pagination_parameters.urlencode(),
    })


@login_required(login_url='login')
def category_list(request):
    categories = Category.objects.annotate(product_count=Count('products')).order_by('name')
    return render(request, 'inventory/category_list.html', {'categories': categories})


@login_required(login_url='login')
def category_add(request):
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category created successfully.')
            return redirect('category_list')
    else:
        form = CategoryForm()
    return render(request, 'inventory/category_form.html', {
        'form': form,
        'title': 'Add category',
    })


@login_required(login_url='login')
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated successfully.')
            return redirect('category_list')
    else:
        form = CategoryForm(instance=category)
    return render(request, 'inventory/category_form.html', {
        'form': form,
        'title': 'Edit category',
    })


@login_required(login_url='login')
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            if category.products.exists():
                messages.error(
                    request,
                    f'Cannot delete "{category.name}" because it has products assigned. '
                    'Reassign those products before deleting this category.',
                )
                return redirect('category_list')
            category.delete()
        messages.success(request, 'Category deleted successfully.')
        return redirect('category_list')

    if category.products.exists():
        messages.error(
            request,
            f'Cannot delete "{category.name}" because it has products assigned. '
            'Reassign those products before deleting this category.',
        )
        return redirect('category_list')
    return render(request, 'inventory/category_confirm_delete.html', {
        'category': category,
    })


@login_required(login_url='login')
def product_add(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            starting_quantity = form.cleaned_data['quantity']
            with transaction.atomic():
                product = form.save(commit=False)
                product.quantity = 0
                product.save()
                form.save_m2m()
                if starting_quantity:
                    apply_stock_movement(
                        product,
                        StockMovement.MovementType.IN,
                        starting_quantity,
                        'Opening stock',
                        request.user,
                    )
            messages.success(request, 'Product created successfully.')
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'inventory/product_form.html', {'form': form, 'title': 'Add Product'})


@login_required(login_url='login')
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated successfully.')
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'inventory/product_form.html', {
        'form': form,
        'title': 'Edit Product',
        'product': product,
    })


@login_required(login_url='login')
def product_delete(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied
    product = get_object_or_404(Product, pk=pk)
    if product.stock_movements.exists():
        messages.error(
            request,
            'This product has stock movement history and cannot be deleted.',
        )
        return redirect('product_list')
    if request.method == 'POST':
        try:
            product.delete()
        except ProtectedError:
            messages.error(
                request,
                'This product has stock movement history and cannot be deleted.',
            )
            return redirect('product_list')
        messages.success(request, 'Product deleted successfully.')
        return redirect('product_list')
    return render(request, 'inventory/product_confirm_delete.html', {'product': product})


@login_required(login_url='login')
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related('category', 'unit', 'supplier'),
        pk=pk,
    )
    movements = product.stock_movements.select_related('created_by')
    return render(request, 'inventory/product_detail.html', {
        'product': product,
        'movements': movements,
    })


@login_required(login_url='login')
def supplier_list(request):
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    suppliers = Supplier.objects.annotate(
        product_count=Count('products'),
    ).order_by('name')
    if query:
        suppliers = suppliers.filter(
            Q(name__icontains=query)
            | Q(phone__icontains=query)
            | Q(city__icontains=query),
        )
    if status_filter == 'active':
        suppliers = suppliers.filter(is_active=True)
    elif status_filter == 'inactive':
        suppliers = suppliers.filter(is_active=False)
    else:
        status_filter = ''

    page_obj = Paginator(suppliers, 20).get_page(request.GET.get('page'))
    pagination_parameters = request.GET.copy()
    pagination_parameters.pop('page', None)
    return render(request, 'inventory/supplier_list.html', {
        'suppliers': page_obj.object_list,
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'pagination_query': pagination_parameters.urlencode(),
    })


@login_required(login_url='login')
def supplier_add(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, 'Supplier created successfully.')
            return redirect('supplier_detail', pk=supplier.pk)
    else:
        form = SupplierForm()
    return render(request, 'inventory/supplier_form.html', {
        'form': form,
        'title': 'Add supplier',
    })


@login_required(login_url='login')
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, 'Supplier updated successfully.')
            return redirect('supplier_detail', pk=supplier.pk)
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'inventory/supplier_form.html', {
        'form': form,
        'title': 'Edit supplier',
        'supplier': supplier,
    })


@login_required(login_url='login')
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    products = supplier.products.select_related('category', 'unit').order_by('name')
    stock_value = products.aggregate(
        total=Sum(F('selling_price') * F('quantity')),
    )['total'] or 0
    return render(request, 'inventory/supplier_detail.html', {
        'supplier': supplier,
        'products': products,
        'stock_value': stock_value,
        'product_count': products.count(),
    })


@login_required(login_url='login')
def supplier_delete(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        if supplier.products.exists():
            messages.error(
                request,
                f'Cannot delete "{supplier.name}" while it has products. '
                'Mark the supplier inactive instead.',
            )
            return redirect('supplier_detail', pk=supplier.pk)
        supplier.delete()
        messages.success(request, 'Supplier deleted successfully.')
        return redirect('supplier_list')
    return render(request, 'inventory/supplier_confirm_delete.html', {
        'supplier': supplier,
        'has_products': supplier.products.exists(),
    })


@login_required(login_url='login')
def stock_movement_list(request):
    movements = StockMovement.objects.select_related('product', 'created_by')
    query = request.GET.get('q', '').strip()
    product_filter = request.GET.get('product', '')
    type_filter = request.GET.get('type', '')
    user_filter = request.GET.get('user', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if query:
        movements = movements.filter(
            Q(product__name__icontains=query)
            | Q(product__sku__icontains=query)
            | Q(reason__icontains=query)
            | Q(note__icontains=query)
            | Q(reference__icontains=query)
            | Q(created_by__username__icontains=query)
        )
    if product_filter.isdigit():
        movements = movements.filter(product_id=product_filter)
    else:
        product_filter = ''
    if type_filter in StockMovement.MovementType.values:
        movements = movements.filter(movement_type=type_filter)
    else:
        type_filter = ''
    if user_filter.isdigit():
        movements = movements.filter(created_by_id=user_filter)
    else:
        user_filter = ''

    try:
        parsed_start = date.fromisoformat(start_date) if start_date else None
    except ValueError:
        parsed_start = None
        start_date = ''
    try:
        parsed_end = date.fromisoformat(end_date) if end_date else None
    except ValueError:
        parsed_end = None
        end_date = ''
    if parsed_start:
        movements = movements.filter(created_at__date__gte=parsed_start)
    if parsed_end:
        movements = movements.filter(created_at__date__lte=parsed_end)

    page_obj = Paginator(movements, 20).get_page(request.GET.get('page'))
    pagination_parameters = request.GET.copy()
    pagination_parameters.pop('page', None)
    return render(request, 'inventory/stock_movement_list.html', {
        'movements': page_obj.object_list,
        'page_obj': page_obj,
        'query': query,
        'products': Product.objects.order_by('name'),
        'users': get_user_model().objects.order_by('username'),
        'product_filter': product_filter,
        'type_filter': type_filter,
        'user_filter': user_filter,
        'movement_types': StockMovement.MovementType.choices,
        'start_date': start_date,
        'end_date': end_date,
        'pagination_query': pagination_parameters.urlencode(),
    })


def _stock_movement_form(request, movement_type, title):
    selected_product = request.GET.get('product', '')
    initial = {}
    if selected_product.isdigit() and Product.objects.filter(pk=selected_product).exists():
        initial['product'] = selected_product

    if request.method == 'POST':
        form = StockMovementForm(
            request.POST,
            movement_type=movement_type,
        )
        if form.is_valid():
            try:
                movement = apply_stock_movement(
                    form.cleaned_data['product'],
                    movement_type,
                    form.cleaned_data['quantity'],
                    form.cleaned_data['reason'],
                    request.user,
                    note=form.cleaned_data['note'],
                    reference=form.cleaned_data['reference'],
                )
            except StockMovementError as error:
                form.add_error('quantity', str(error))
            else:
                messages.success(request, 'Stock movement recorded successfully.')
                return redirect('product_detail', pk=movement.product_id)
    else:
        form = StockMovementForm(
            movement_type=movement_type,
            initial=initial,
        )

    return render(request, 'inventory/stock_movement_form.html', {
        'form': form,
        'movement_type': movement_type,
        'title': title,
    })


@login_required(login_url='login')
def stock_in(request):
    return _stock_movement_form(request, StockMovement.MovementType.IN, 'Stock In')


@login_required(login_url='login')
def stock_out(request):
    return _stock_movement_form(request, StockMovement.MovementType.OUT, 'Stock Out')


@login_required(login_url='login')
def stock_adjust(request):
    return _stock_movement_form(request, StockMovement.MovementType.ADJUST, 'Adjust Stock')