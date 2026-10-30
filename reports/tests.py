import csv
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from inventory.models import Category, Product, StockMovement, Supplier, Unit
from inventory.services import apply_stock_movement

from . import services


class ReportServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='report-user',
            password='Report-password-509!',
        )
        self.category = Category.objects.create(name='Report category')
        self.supplier = Supplier.objects.create(name='Report supplier')
        self.unit = Unit.objects.get(name='Piece')

    def create_product(
        self,
        *,
        name,
        sku,
        quantity=0,
        cost_price='2.00',
        selling_price='5.00',
        threshold=5,
        category=None,
        supplier=None,
        active=True,
    ):
        product = Product.objects.create(
            name=name,
            sku=sku,
            category=category,
            supplier=supplier,
            unit=self.unit,
            cost_price=Decimal(cost_price),
            selling_price=Decimal(selling_price),
            quantity=0,
            low_stock_threshold=threshold,
            is_active=active,
        )
        if quantity:
            apply_stock_movement(
                product,
                StockMovement.MovementType.IN,
                quantity,
                'Opening stock',
                self.user,
            )
        return product

    def test_stock_valuation_totals_and_category_values(self):
        self.create_product(
            name='First report product',
            sku='REPORT-001',
            quantity=4,
            category=self.category,
            supplier=self.supplier,
        )
        self.create_product(
            name='Second report product',
            sku='REPORT-002',
            quantity=2,
            cost_price='3.00',
            selling_price='7.00',
        )

        report = services.get_stock_valuation()

        self.assertEqual(report['totals']['total_cost_value'], Decimal('14.00'))
        self.assertEqual(report['totals']['total_retail_value'], Decimal('34.00'))
        self.assertEqual(report['totals']['total_potential_profit'], Decimal('20.00'))
        self.assertEqual(report['totals']['total_units'], 6)
        self.assertEqual(
            {item['label']: Decimal(item['value']) for item in report['chart_data']},
            {'Report category': Decimal('8.00'), 'Uncategorized': Decimal('6.00')},
        )

    def test_movement_report_totals_match_filtered_ledger_entries(self):
        product = self.create_product(
            name='Movement product',
            sku='MOVE-001',
            category=self.category,
        )
        apply_stock_movement(
            product,
            StockMovement.MovementType.IN,
            10,
            'Purchase',
            self.user,
        )
        apply_stock_movement(
            product,
            StockMovement.MovementType.IN,
            5,
            'Customer return',
            self.user,
        )
        apply_stock_movement(
            product,
            StockMovement.MovementType.OUT,
            3,
            'Sale',
            self.user,
        )
        apply_stock_movement(
            product,
            StockMovement.MovementType.ADJUST,
            8,
            'Stock count correction',
            self.user,
        )

        today = timezone.localdate().isoformat()
        report = services.get_stock_movement_report({
            'start_date': today,
            'end_date': today,
            'category': self.category.pk,
            'product': product.pk,
        })

        self.assertEqual(report['totals']['total_in'], 15)
        self.assertEqual(report['totals']['total_out'], 3)
        self.assertEqual(report['totals']['net_change'], 8)
        self.assertEqual(report['totals']['movement_count'], 4)

    def test_invalid_and_empty_date_ranges_are_handled(self):
        invalid = services.get_stock_movement_report({
            'start_date': 'not-a-date',
            'end_date': 'also-invalid',
        })
        self.assertIn('invalid', invalid['filters']['date_error'])
        self.assertEqual(invalid['totals']['movement_count'], 0)

        empty_range = services.get_stock_movement_report({
            'start_date': '2026-10-30',
            'end_date': '2026-10-29',
        })
        self.assertIn('on or before', empty_range['filters']['date_error'])
        self.assertEqual(empty_range['totals']['movement_count'], 0)
        self.assertEqual(empty_range['chart_data'], [])

    def test_low_stock_report_threshold_active_filter_and_reorder_formula(self):
        at_threshold = self.create_product(
            name='At threshold',
            sku='LOW-001',
            quantity=5,
            threshold=5,
        )
        out_of_stock = self.create_product(
            name='Out of stock',
            sku='LOW-002',
            quantity=0,
            threshold=0,
        )
        self.create_product(
            name='Above threshold',
            sku='LOW-003',
            quantity=6,
            threshold=5,
        )
        self.create_product(
            name='Inactive low stock',
            sku='LOW-004',
            quantity=1,
            threshold=5,
            active=False,
        )

        report = services.get_low_stock_report()
        result = {product.pk: product for product in report['products']}

        self.assertEqual(set(result), {at_threshold.pk, out_of_stock.pk})
        self.assertEqual(result[at_threshold.pk].suggested_reorder, 5)
        self.assertEqual(result[out_of_stock.pk].suggested_reorder, 1)

    def test_supplier_report_totals(self):
        self.create_product(
            name='Supplier product one',
            sku='SUP-REPORT-001',
            quantity=5,
            cost_price='2.00',
            threshold=5,
            supplier=self.supplier,
        )
        self.create_product(
            name='Supplier product two',
            sku='SUP-REPORT-002',
            quantity=3,
            cost_price='1.00',
            threshold=4,
            supplier=self.supplier,
        )

        report = services.get_supplier_stock_report()
        supplier = report['suppliers'].get(pk=self.supplier.pk)

        self.assertEqual(supplier.product_count, 2)
        self.assertEqual(supplier.total_units, 8)
        self.assertEqual(supplier.total_cost_value, Decimal('13.00'))
        self.assertEqual(supplier.low_stock_count, 2)
        self.assertEqual(report['totals']['supplier_count'], 1)
        self.assertEqual(report['totals']['product_count'], 2)
        self.assertEqual(report['totals']['total_cost_value'], Decimal('13.00'))

    def test_csv_injection_protection_preserves_numeric_values(self):
        for value in ('=1+1', '+cmd', '-danger', '@formula'):
            with self.subTest(value=value):
                self.assertEqual(services.csv_safe(value), f"'{value}")
        self.assertEqual(services.csv_safe(-4), '-4')


class ReportViewTests(ReportServiceTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_csv_export_respects_valuation_filters_and_has_utf8_bom(self):
        matching = self.create_product(
            name='Matching CSV row',
            sku='CSV-001',
            category=self.category,
        )
        self.create_product(name='Other CSV row', sku='CSV-002')

        response = self.client.get(
            reverse('reports:stock_valuation'),
            {'category': self.category.pk, 'export': 'csv'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('stock_valuation_', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], matching.name)

    def test_csv_export_escapes_formula_like_text(self):
        product = self.create_product(
            name='=HYPERLINK("https://example.test")',
            sku='CSV-INJECT-1',
            category=self.category,
        )

        response = self.client.get(
            reverse('reports:stock_valuation'),
            {'category': self.category.pk, 'export': 'csv'},
        )

        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(rows[1][0], f"'{product.name}")

    def test_all_report_pages_and_exports_require_login(self):
        urls = (
            reverse('reports:hub'),
            reverse('reports:stock_valuation'),
            reverse('reports:stock_movement_report'),
            reverse('reports:low_stock_report'),
            reverse('reports:supplier_stock_report'),
            reverse('reports:stock_valuation') + '?export=csv',
            reverse('reports:stock_movement_report') + '?export=csv',
            reverse('reports:low_stock_report') + '?export=csv',
            reverse('reports:supplier_stock_report') + '?export=csv',
        )
        self.client.logout()

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response.url)

    def test_report_templates_render_and_include_report_hub_cards(self):
        report_urls = (
            reverse('reports:hub'),
            reverse('reports:stock_valuation'),
            reverse('reports:stock_movement_report'),
            reverse('reports:low_stock_report'),
            reverse('reports:supplier_stock_report'),
        )
        for url in report_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Reports')

        hub_response = self.client.get(reverse('reports:hub'))
        self.assertContains(hub_response, 'Stock Valuation')
        self.assertContains(hub_response, 'Stock Movement Report')
        self.assertContains(hub_response, 'Low Stock Report')
        self.assertContains(hub_response, 'Supplier-wise Stock')
