from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F
from .models import Product
from .forms import ProductForm


@login_required(login_url='login')
def dashboard(request):
    total_products = Product.objects.count()
    total_stock_value = Product.objects.aggregate(
        total=Sum(F('price') * F('quantity'))
    )['total'] or 0
    low_stock_products = Product.objects.filter(quantity__lt=F('low_stock_threshold'))

    context = {
        'total_products': total_products,
        'total_stock_value': total_stock_value,
        'low_stock_products': low_stock_products,
        'low_stock_count': low_stock_products.count(),
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required(login_url='login')
def product_list(request):
    query = request.GET.get('q', '')
    products = Product.objects.all().order_by('-created_at')
    if query:
        products = products.filter(name__icontains=query) | products.filter(sku__icontains=query)
    return render(request, 'inventory/product_list.html', {'products': products, 'query': query})


@login_required(login_url='login')
def product_add(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'inventory/product_form.html', {'form': form, 'title': 'Add Product'})


@login_required(login_url='login')
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'inventory/product_form.html', {'form': form, 'title': 'Edit Product'})


@login_required(login_url='login')
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        product.delete()
        return redirect('product_list')
    return render(request, 'inventory/product_confirm_delete.html', {'product': product})