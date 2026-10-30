from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import Category, Product, StockMovement, Supplier, Unit
from inventory.services import apply_stock_movement


SAMPLE_PRODUCTS = (
    {
        'name': 'Wireless Headphones',
        'sku': 'DEMO-001',
        'category': 'Electronics',
        'unit': 'Piece',
        'supplier_name': 'Soundwave Supply',
        'description': 'Over-ear wireless headphones with noise isolation.',
        'cost_price': '34.00',
        'selling_price': '59.99',
        'quantity': 24,
        'low_stock_threshold': 8,
    },
    {
        'name': 'USB-C Charging Cable',
        'sku': 'DEMO-002',
        'category': 'Electronics',
        'unit': 'Piece',
        'supplier_name': 'ConnectSource',
        'description': 'One-metre braided USB-C charging cable.',
        'cost_price': '4.25',
        'selling_price': '9.99',
        'quantity': 42,
        'low_stock_threshold': 12,
    },
    {
        'name': 'Bluetooth Keyboard',
        'sku': 'DEMO-003',
        'category': 'Electronics',
        'unit': 'Piece',
        'supplier_name': 'Keyline Wholesale',
        'description': 'Compact Bluetooth keyboard for everyday work.',
        'cost_price': '21.00',
        'selling_price': '39.50',
        'quantity': 7,
        'low_stock_threshold': 10,
    },
    {
        'name': 'Ceramic Coffee Mug',
        'sku': 'DEMO-004',
        'category': 'Kitchenware',
        'unit': 'Piece',
        'supplier_name': 'Hearth & Home',
        'description': 'Durable 350 ml ceramic mug.',
        'cost_price': '3.50',
        'selling_price': '8.00',
        'quantity': 36,
        'low_stock_threshold': 10,
    },
    {
        'name': 'Glass Storage Jars',
        'sku': 'DEMO-005',
        'category': 'Kitchenware',
        'unit': 'Pair',
        'supplier_name': 'Hearth & Home',
        'description': 'Set of two clear glass pantry jars.',
        'cost_price': '9.00',
        'selling_price': '16.50',
        'quantity': 14,
        'low_stock_threshold': 5,
    },
    {
        'name': 'Cotton T-Shirt',
        'sku': 'DEMO-006',
        'category': 'Clothing',
        'unit': 'Piece',
        'supplier_name': 'Everyday Apparel',
        'description': 'Soft cotton crew-neck T-shirt.',
        'cost_price': '7.50',
        'selling_price': '15.00',
        'quantity': 28,
        'low_stock_threshold': 8,
    },
    {
        'name': 'Canvas Tote Bag',
        'sku': 'DEMO-007',
        'category': 'Clothing',
        'unit': 'Piece',
        'supplier_name': 'Everyday Apparel',
        'description': 'Reusable heavy-canvas carry bag.',
        'cost_price': '5.00',
        'selling_price': '12.00',
        'quantity': 4,
        'low_stock_threshold': 6,
    },
    {
        'name': 'Running Shoe Laces',
        'sku': 'DEMO-008',
        'category': 'Footwear',
        'unit': 'Pair',
        'supplier_name': 'Stride Wholesale',
        'description': 'Replacement laces sold as a pair.',
        'cost_price': '2.00',
        'selling_price': '5.50',
        'quantity': 18,
        'low_stock_threshold': 6,
    },
    {
        'name': 'Training Resistance Bands',
        'sku': 'DEMO-009',
        'category': 'Fitness',
        'unit': 'Pair',
        'supplier_name': 'Active Goods',
        'description': 'Two resistance bands for home workouts.',
        'cost_price': '6.50',
        'selling_price': '14.00',
        'quantity': 11,
        'low_stock_threshold': 5,
    },
    {
        'name': 'Stainless Water Bottle',
        'sku': 'DEMO-010',
        'category': 'Fitness',
        'unit': 'Piece',
        'supplier_name': 'Active Goods',
        'description': 'Insulated 750 ml stainless-steel bottle.',
        'cost_price': '11.00',
        'selling_price': '24.00',
        'quantity': 20,
        'low_stock_threshold': 7,
    },
    {
        'name': 'Wireless Mouse',
        'sku': 'DEMO-011',
        'category': 'Electronics',
        'unit': 'Piece',
        'supplier_name': 'ConnectSource',
        'description': 'Ergonomic wireless mouse with USB receiver.',
        'cost_price': '12.00',
        'selling_price': '25.00',
        'quantity': 0,
        'low_stock_threshold': 5,
        'is_active': False,
    },
    {
        'name': 'Meal Prep Container Set',
        'sku': 'DEMO-012',
        'category': 'Kitchenware',
        'unit': 'Pair',
        'supplier_name': 'Hearth & Home',
        'description': 'Reusable food containers sold as a pair.',
        'cost_price': '8.00',
        'selling_price': '17.00',
        'quantity': 9,
        'low_stock_threshold': 4,
    },
)


class Command(BaseCommand):
    help = 'Create twelve sample products without overwriting existing catalog data.'

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0

        with transaction.atomic():
            for sample in SAMPLE_PRODUCTS:
                category, _ = Category.objects.get_or_create(name=sample['category'])
                unit = Unit.objects.get(name=sample['unit'])
                supplier, _ = Supplier.objects.get_or_create(
                    name=sample['supplier_name'],
                )
                defaults = {
                    key: value
                    for key, value in sample.items()
                    if key not in {'sku', 'category', 'unit', 'supplier_name', 'quantity'}
                }
                starting_quantity = sample['quantity']
                defaults['quantity'] = 0
                defaults['cost_price'] = Decimal(defaults['cost_price'])
                defaults['selling_price'] = Decimal(defaults['selling_price'])
                product, created = Product.objects.get_or_create(
                    sku=sample['sku'],
                    defaults={
                        **defaults,
                        'category': category,
                        'unit': unit,
                        'supplier': supplier,
                    },
                )
                if created:
                    created_count += 1
                    if starting_quantity:
                        creator = (
                            get_user_model().objects
                            .filter(is_superuser=True)
                            .order_by('pk')
                            .first()
                        )
                        if creator is None:
                            raise CommandError(
                                'Create a superuser before seeding products with '
                                'starting stock.'
                            )
                        apply_stock_movement(
                            product,
                            StockMovement.MovementType.IN,
                            starting_quantity,
                            'Opening stock',
                            creator,
                        )
                else:
                    existing_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Sample products ready: {created_count} created, {existing_count} already existed.'
        ))
