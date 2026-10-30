from django.contrib import admin
from .models import Category, Product, StockMovement, Supplier, Unit


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name', 'description')


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_code')
    search_fields = ('name', 'short_code')


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone', 'city', 'payment_terms', 'is_active')
    list_filter = ('is_active', 'payment_terms', 'city')
    search_fields = ('name', 'phone', 'city', 'email')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'sku',
        'category',
        'unit',
        'supplier',
        'selling_price',
        'quantity',
        'is_active',
        'created_at',
    )
    list_filter = ('is_active', 'category', 'unit')
    search_fields = ('name', 'sku', 'supplier__name')
    readonly_fields = ('quantity',)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'product',
        'movement_type',
        'quantity_change',
        'quantity_before',
        'quantity_after',
        'reason',
        'created_by',
    )
    list_filter = ('movement_type', 'reason', 'created_at')
    search_fields = ('product__name', 'product__sku', 'reference', 'created_by__username')
    readonly_fields = (
        'product',
        'movement_type',
        'quantity',
        'quantity_change',
        'quantity_before',
        'quantity_after',
        'reason',
        'note',
        'reference',
        'created_by',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False