from django.contrib import admin
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'supplier_name', 'price', 'quantity', 'low_stock_threshold', 'created_at')
    search_fields = ('name', 'sku', 'supplier_name')