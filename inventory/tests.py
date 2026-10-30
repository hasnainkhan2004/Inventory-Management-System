from io import BytesIO
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core import mail
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .forms import ProductForm, SupplierForm
from .models import Category, Product, StockMovement, Supplier, Unit
from .services import StockMovementError, apply_stock_movement


class AuthenticationTests(TestCase):
    def test_authentication_pages_do_not_show_navigation_bar(self):
        pages = (
            reverse('login'),
            reverse('signup'),
            reverse('password_reset'),
            reverse('password_reset_done'),
            reverse(
                'password_reset_confirm',
                kwargs={'uidb64': 'MQ', 'token': 'invalid-token'},
            ),
            reverse('password_reset_complete'),
        )
        for page in pages:
            with self.subTest(page=page):
                response = self.client.get(page)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, '<nav', html=False)

    def test_signup_creates_account_and_logs_user_in(self):
        response = self.client.post(reverse('signup'), {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'A-strong-password-502!',
            'password2': 'A-strong-password-502!',
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(self.client.session.get('_auth_user_id'))
        user = get_user_model().objects.get(username='newuser')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertNotContains(self.client.get(reverse('dashboard')), 'Go to Admin Panel')

    def test_staff_user_sees_admin_panel_link(self):
        user = get_user_model().objects.create_user(
            username='staffuser',
            email='staffuser@example.com',
            password='A-strong-password-502!',
            is_staff=True,
        )
        self.client.force_login(user)

        self.assertContains(self.client.get(reverse('dashboard')), 'Go to Admin Panel')

    def test_signup_rejects_an_existing_email_case_insensitively(self):
        get_user_model().objects.create_user(
            username='existing',
            email='person@example.com',
            password='A-strong-password-502!',
        )

        response = self.client.post(reverse('signup'), {
            'username': 'anotheruser',
            'email': 'PERSON@example.com',
            'password1': 'A-strong-password-502!',
            'password2': 'A-strong-password-502!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'An account with this email already exists.')
        self.assertFalse(get_user_model().objects.filter(username='anotheruser').exists())

    def test_login_accepts_email_address(self):
        get_user_model().objects.create_user(
            username='emailuser',
            email='emailuser@example.com',
            password='A-strong-password-502!',
        )

        response = self.client.post(reverse('login'), {
            'username': 'emailuser@example.com',
            'password': 'A-strong-password-502!',
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_login_accepts_username(self):
        get_user_model().objects.create_user(
            username='nameuser',
            email='nameuser@example.com',
            password='A-strong-password-502!',
        )

        response = self.client.post(reverse('login'), {
            'username': 'nameuser',
            'password': 'A-strong-password-502!',
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_login_rejects_invalid_credentials(self):
        response = self.client.post(reverse('login'), {
            'username': 'nobody',
            'password': 'not-the-password',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username/email or password. Please try again.')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_changes_password_using_email_link(self):
        user = get_user_model().objects.create_user(
            username='resetuser',
            email='resetuser@example.com',
            password='A-strong-password-502!',
        )

        response = self.client.post(reverse('password_reset'), {
            'email': 'resetuser@example.com',
        })

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('resetuser@example.com', mail.outbox[0].to)
        reset_url = next(
            line for line in mail.outbox[0].body.splitlines()
            if '/reset/' in line
        )
        reset_path = urlparse(reset_url).path

        response = self.client.get(reset_path, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a new password')

        response = self.client.post(response.request['PATH_INFO'], {
            'new_password1': 'A-different-password-811!',
            'new_password2': 'A-different-password-811!',
        })

        self.assertRedirects(response, reverse('password_reset_complete'))
        user.refresh_from_db()
        self.assertTrue(user.check_password('A-different-password-811!'))
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.get(reset_path)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This reset link is no longer valid')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_unknown_email_receives_same_generic_confirmation(self):
        get_user_model().objects.create_user(
            username='knownuser',
            email='known@example.com',
            password='A-strong-password-502!',
        )

        known_response = self.client.post(reverse('password_reset'), {
            'email': 'known@example.com',
        })
        self.assertRedirects(known_response, reverse('password_reset_done'))
        self.assertContains(
            self.client.get(reverse('password_reset_done')),
            'If an account with that email exists',
        )
        self.assertEqual(len(mail.outbox), 1)

        unknown_response = self.client.post(reverse('password_reset'), {
            'email': 'unknown@example.com',
        })

        self.assertRedirects(unknown_response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(
            self.client.get(reverse('password_reset_done')),
            'If an account with that email exists',
        )


class InventoryManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='inventoryuser',
            password='A-strong-password-502!',
        )
        get_user_model().objects.create_superuser(
            username='inventoryadmin',
            email='inventoryadmin@example.com',
            password='A-strong-password-502!',
        )
        self.client.force_login(self.user)
        self.piece = Unit.objects.get(name='Piece')

    def create_product(
        self,
        *,
        name,
        sku='',
        category=None,
        supplier=None,
        is_active=True,
        quantity=5,
    ):
        product = Product.objects.create(
            name=name,
            sku=sku,
            category=category,
            supplier=supplier,
            unit=self.piece,
            selling_price=Decimal('12.50'),
            cost_price=Decimal('8.00'),
            quantity=0,
            is_active=is_active,
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

    def test_stock_in_increases_quantity_and_records_snapshots(self):
        product = self.create_product(name='Inbound item', quantity=5)

        movement = apply_stock_movement(
            product,
            StockMovement.MovementType.IN,
            3,
            'Purchase',
            self.user,
            reference='PO-123',
        )

        product.refresh_from_db()
        self.assertEqual(product.quantity, 8)
        self.assertEqual(movement.quantity_change, 3)
        self.assertEqual((movement.quantity_before, movement.quantity_after), (5, 8))
        self.assertEqual(movement.reference, 'PO-123')

    def test_stock_out_decreases_quantity_and_records_snapshots(self):
        product = self.create_product(name='Outbound item', quantity=5)

        movement = apply_stock_movement(
            product,
            StockMovement.MovementType.OUT,
            2,
            'Sale',
            self.user,
        )

        product.refresh_from_db()
        self.assertEqual(product.quantity, 3)
        self.assertEqual(movement.quantity_change, -2)
        self.assertEqual((movement.quantity_before, movement.quantity_after), (5, 3))

    def test_stock_out_beyond_available_quantity_is_rejected(self):
        product = self.create_product(name='Limited item', quantity=2)
        prior_count = StockMovement.objects.filter(product=product).count()

        with self.assertRaisesRegex(StockMovementError, 'only 2 are available'):
            apply_stock_movement(
                product,
                StockMovement.MovementType.OUT,
                3,
                'Sale',
                self.user,
            )

        product.refresh_from_db()
        self.assertEqual(product.quantity, 2)
        self.assertEqual(StockMovement.objects.filter(product=product).count(), prior_count)

    def test_adjustment_records_the_signed_difference_from_new_count(self):
        product = self.create_product(name='Counted item', quantity=5)

        movement = apply_stock_movement(
            product,
            StockMovement.MovementType.ADJUST,
            8,
            'Stock count correction',
            self.user,
        )

        product.refresh_from_db()
        self.assertEqual(product.quantity, 8)
        self.assertEqual(movement.quantity, 3)
        self.assertEqual(movement.quantity_change, 3)
        self.assertEqual((movement.quantity_before, movement.quantity_after), (5, 8))

    def test_stock_movement_cannot_be_edited_or_deleted(self):
        product = self.create_product(name='Immutable movement')
        movement = StockMovement.objects.get(product=product)

        movement.note = 'Changed after recording'
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            movement.save()
        with self.assertRaisesRegex(ValidationError, 'cannot be deleted'):
            movement.delete()
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            StockMovement.objects.filter(pk=movement.pk).update(note='Changed')
        with self.assertRaisesRegex(ValidationError, 'cannot be deleted'):
            StockMovement.objects.filter(pk=movement.pk).delete()

    def test_stock_movement_admin_is_read_only(self):
        product = self.create_product(name='Admin movement')
        movement = StockMovement.objects.get(product=product)
        admin_user = get_user_model().objects.get(username='inventoryadmin')
        self.client.force_login(admin_user)

        for route_name, kwargs in (
            ('admin:inventory_stockmovement_add', {}),
            ('admin:inventory_stockmovement_delete', {'object_id': movement.pk}),
        ):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name, kwargs=kwargs))
                self.assertEqual(response.status_code, 403)

        change_url = reverse(
            'admin:inventory_stockmovement_change',
            kwargs={'object_id': movement.pk},
        )
        self.assertEqual(self.client.get(change_url).status_code, 200)
        self.client.post(change_url, {'note': 'Changed from admin', '_save': 'Save'})
        movement.refresh_from_db()
        self.assertEqual(movement.note, '')

    def test_new_product_starting_quantity_creates_opening_movement(self):
        response = self.client.post(reverse('product_add'), {
            'name': 'Starting stock item',
            'sku': 'START-001',
            'category': '',
            'unit': self.piece.pk,
            'supplier': '',
            'description': '',
            'cost_price': '1.00',
            'selling_price': '2.00',
            'quantity': '6',
            'low_stock_threshold': '2',
            'is_active': 'on',
        })

        product = Product.objects.get(sku='START-001')
        movement = StockMovement.objects.get(product=product)
        self.assertRedirects(response, reverse('product_list'))
        self.assertEqual(product.quantity, 6)
        self.assertEqual(movement.reason, 'Opening stock')
        self.assertEqual(movement.created_by, self.user)
        self.assertEqual((movement.quantity_before, movement.quantity_after), (0, 6))

    def test_product_edit_quantity_is_read_only_and_links_to_adjustment(self):
        product = self.create_product(name='Read-only quantity', quantity=5)

        response = self.client.get(reverse('product_edit', kwargs={'pk': product.pk}))

        self.assertNotContains(response, 'name="quantity"', html=False)
        self.assertContains(response, 'Current stock')
        self.assertContains(response, reverse('stock_adjust') + f'?product={product.pk}')

    def test_product_cannot_be_deleted_after_a_stock_movement(self):
        product = self.create_product(name='Protected product')
        staff_user = get_user_model().objects.create_user(
            username='productdeleter',
            password='A-strong-password-502!',
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.post(
            reverse('product_delete', kwargs={'pk': product.pk}),
            follow=True,
        )

        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertContains(response, 'stock movement history and cannot be deleted')

    def test_movement_list_filters_by_product_type_and_search(self):
        product = self.create_product(name='Filter ledger item', quantity=4)
        apply_stock_movement(
            product,
            StockMovement.MovementType.OUT,
            1,
            'Sale',
            self.user,
            reference='INV-SEARCH-1',
        )

        response = self.client.get(reverse('stock_movement_list'), {
            'q': 'INV-SEARCH-1',
            'product': product.pk,
            'type': StockMovement.MovementType.OUT,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_stock_out_form_shows_available_quantity_error(self):
        product = self.create_product(name='Form stock limit', quantity=2)

        response = self.client.post(reverse('stock_out'), {
            'product': product.pk,
            'quantity': '3',
            'reason': 'Sale',
            'note': '',
            'reference': '',
        })

        product.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'only 2 are available')
        self.assertEqual(product.quantity, 2)

    def test_adjustment_form_preselects_product_and_shows_count_label(self):
        product = self.create_product(name='Adjust form item', quantity=5)

        response = self.client.get(
            reverse('stock_adjust'),
            {'product': product.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Counted quantity')
        self.assertContains(response, 'data-current-stock="5"')
        self.assertEqual(response.context['form']['product'].value(), str(product.pk))

    def test_product_detail_shows_stock_movement_history(self):
        product = self.create_product(name='Product history item', quantity=5)

        response = self.client.get(
            reverse('product_detail', kwargs={'pk': product.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Movement history')
        self.assertContains(response, 'Opening stock')

    def test_sku_is_generated_from_category_and_sequence(self):
        category = Category.objects.create(name='Electronics')

        first = self.create_product(name='Adapter', category=category)
        second = self.create_product(name='Cable', category=category)
        uncategorized = self.create_product(name='Misc item')
        manual = self.create_product(name='Custom item', sku='CUSTOM-001')

        self.assertEqual(first.sku, 'ELE-0001')
        self.assertEqual(second.sku, 'ELE-0002')
        self.assertEqual(uncategorized.sku, 'GEN-0001')
        self.assertEqual(manual.sku, 'CUSTOM-001')

    def test_category_with_products_cannot_be_deleted(self):
        category = Category.objects.create(name='Accessories')
        self.create_product(name='Mouse', category=category)
        self.assertEqual(category.products.count(), 1)

        response = self.client.get(
            reverse('category_delete', kwargs={'pk': category.pk}),
            follow=True,
        )

        self.assertEqual(
            [str(message) for message in response.context['messages']],
            [
                'Cannot delete "Accessories" because it has products assigned. '
                'Reassign those products before deleting this category.'
            ],
        )
        self.assertContains(response, 'Reassign those products before deleting this category.')
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())

    def test_category_can_be_created_edited_and_deleted(self):
        self.assertEqual(self.client.get(reverse('category_add')).status_code, 200)
        response = self.client.post(reverse('category_add'), {
            'name': 'Accessories',
            'description': 'Small peripherals',
        })
        category = Category.objects.get(name='Accessories')
        self.assertRedirects(response, reverse('category_list'))

        response = self.client.post(
            reverse('category_edit', kwargs={'pk': category.pk}),
            {
                'name': 'Computer accessories',
                'description': 'Updated description',
            },
        )
        self.assertRedirects(response, reverse('category_list'))
        category.refresh_from_db()
        self.assertEqual(category.name, 'Computer accessories')
        self.assertEqual(category.description, 'Updated description')

        response = self.client.get(
            reverse('category_delete', kwargs={'pk': category.pk}),
        )
        self.assertContains(response, 'Delete this category?')

        response = self.client.post(
            reverse('category_delete', kwargs={'pk': category.pk}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Category.objects.filter(pk=category.pk).exists())

    def test_pair_is_available_as_a_product_unit(self):
        response = self.client.get(reverse('product_add'))

        self.assertContains(response, 'Pair')

    def test_dashboard_chart_data_comes_from_product_categories(self):
        electronics = Category.objects.create(name='Electronics')
        self.create_product(name='Adapter', category=electronics, quantity=7)
        self.create_product(name='Loose item', quantity=3)
        self.create_product(name='Out of stock', category=electronics, quantity=0)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(
            {
                item['label']: item['quantity']
                for item in response.context['stock_by_category']
            },
            {'Electronics': 7, 'Uncategorized': 3},
        )

    def test_product_filters_combine_search_category_and_status(self):
        electronics = Category.objects.create(name='Electronics')
        office = Category.objects.create(name='Office')
        matching = self.create_product(
            name='Filtered adapter',
            category=electronics,
            is_active=True,
        )
        self.create_product(
            name='Filtered inactive adapter',
            category=electronics,
            is_active=False,
        )
        self.create_product(
            name='Filtered office adapter',
            category=office,
            is_active=True,
        )

        response = self.client.get(reverse('product_list'), {
            'q': 'Filtered',
            'category': electronics.pk,
            'status': 'active',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['products']), [matching])

    def test_product_list_has_twenty_items_per_page(self):
        for number in range(21):
            self.create_product(
                name=f'Product {number}',
                sku=f'PAGE-{number:04d}',
            )

        first_page = self.client.get(reverse('product_list'))
        second_page = self.client.get(reverse('product_list'), {'page': 2})

        self.assertEqual(len(first_page.context['products']), 20)
        self.assertEqual(len(second_page.context['products']), 1)

    def test_sample_product_command_is_idempotent(self):
        call_command('seed_sample_products')
        call_command('seed_sample_products')

        sample_products = Product.objects.filter(sku__startswith='DEMO-')
        self.assertEqual(sample_products.count(), 12)
        self.assertEqual(
            sample_products.filter(unit__name='Pair').count(),
            4,
        )

    def test_product_form_rejects_negative_cost_price(self):
        form = ProductForm(data={
            'name': 'Invalid cost',
            'sku': '',
            'category': '',
            'unit': self.piece.pk,
            'supplier': '',
            'description': '',
            'cost_price': '-0.01',
            'selling_price': '1.00',
            'quantity': '1',
            'low_stock_threshold': '1',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('cost_price', form.errors)

    def test_product_form_uploads_image_with_preview_markup(self):
        form_response = self.client.get(reverse('product_add'))
        self.assertContains(form_response, 'data-product-form')
        self.assertContains(form_response, 'data-image-preview')

        image_buffer = BytesIO()
        Image.new('RGB', (2, 2), color='purple').save(image_buffer, format='PNG')
        image_file = SimpleUploadedFile(
            'adapter.png',
            image_buffer.getvalue(),
            content_type='image/png',
        )

        with TemporaryDirectory() as media_directory:
            with override_settings(MEDIA_ROOT=media_directory):
                response = self.client.post(reverse('product_add'), {
                    'name': 'Adapter with image',
                    'sku': '',
                    'category': '',
                    'unit': self.piece.pk,
                    'supplier': '',
                    'description': 'Image upload check',
                    'cost_price': '3.50',
                    'selling_price': '5.00',
                    'quantity': '4',
                    'low_stock_threshold': '1',
                    'is_active': 'on',
                    'image': image_file,
                })

                self.assertRedirects(response, reverse('product_list'))
                product = Product.objects.get(name='Adapter with image')
                self.assertTrue(product.image.name.startswith('products/'))
                self.assertTrue(Path(media_directory, product.image.name).is_file())


class SupplierManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='supplieruser',
            password='A-strong-password-502!',
        )
        self.staff_user = get_user_model().objects.create_user(
            username='supplierstaff',
            password='A-strong-password-502!',
            is_staff=True,
        )
        self.piece = Unit.objects.get(name='Piece')
        self.client.force_login(self.user)

    def create_product(
        self,
        supplier,
        *,
        name='Supplier product',
        sku='SUP-001',
        category=None,
        quantity=5,
    ):
        product = Product.objects.create(
            name=name,
            sku=sku,
            supplier=supplier,
            category=category,
            unit=self.piece,
            selling_price=Decimal('12.00'),
            cost_price=Decimal('8.00'),
            quantity=0,
            low_stock_threshold=2,
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

    def test_supplier_name_must_be_unique(self):
        Supplier.objects.create(name='Unique supplier')

        form = SupplierForm(data={
            'name': 'Unique supplier',
            'contact_person': '',
            'phone': '',
            'email': '',
            'address': '',
            'city': '',
            'payment_terms': Supplier.PaymentTerms.CASH,
            'notes': '',
            'is_active': 'on',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_supplier_form_validates_email_and_phone_characters(self):
        form = SupplierForm(data={
            'name': 'Invalid supplier details',
            'contact_person': '',
            'phone': '123 (555)',
            'email': 'not-an-email',
            'address': '',
            'city': '',
            'payment_terms': Supplier.PaymentTerms.CASH,
            'notes': '',
            'is_active': 'on',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertIn('phone', form.errors)

    def test_supplier_can_be_created_and_edited(self):
        response = self.client.post(reverse('supplier_add'), {
            'name': 'New Supplier',
            'contact_person': 'Alex Vendor',
            'phone': '+1-555-0100',
            'email': 'vendor@example.com',
            'address': '12 Market Street',
            'city': 'Harbor City',
            'payment_terms': Supplier.PaymentTerms.DAYS_15,
            'notes': 'Preferred contact by email',
            'is_active': 'on',
        })
        supplier = Supplier.objects.get(name='New Supplier')
        self.assertRedirects(
            response,
            reverse('supplier_detail', kwargs={'pk': supplier.pk}),
        )

        response = self.client.post(
            reverse('supplier_edit', kwargs={'pk': supplier.pk}),
            {
                'name': 'Updated Supplier',
                'contact_person': 'Alex Vendor',
                'phone': '15550101',
                'email': 'vendor@example.com',
                'address': '12 Market Street',
                'city': 'Harbor City',
                'payment_terms': Supplier.PaymentTerms.DAYS_30,
                'notes': '',
                'is_active': 'on',
            },
        )

        supplier.refresh_from_db()
        self.assertEqual(supplier.name, 'Updated Supplier')
        self.assertEqual(supplier.payment_terms, Supplier.PaymentTerms.DAYS_30)
        self.assertRedirects(
            response,
            reverse('supplier_detail', kwargs={'pk': supplier.pk}),
        )

    def test_product_form_offers_active_suppliers_and_add_link(self):
        active = Supplier.objects.create(name='Active choice')
        Supplier.objects.create(name='Inactive choice', is_active=False)

        response = self.client.get(reverse('product_add'))

        self.assertContains(response, active.name)
        self.assertNotContains(response, 'Inactive choice')
        self.assertContains(response, '+ Add supplier')

    def test_supplier_delete_is_blocked_when_products_exist(self):
        supplier = Supplier.objects.create(name='Assigned supplier')
        self.create_product(supplier)
        self.client.force_login(self.staff_user)

        response = self.client.get(
            reverse('supplier_delete', kwargs={'pk': supplier.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mark this supplier inactive instead')
        self.assertNotContains(response, 'Delete supplier</button>')

        response = self.client.post(
            reverse('supplier_delete', kwargs={'pk': supplier.pk}),
            follow=True,
        )
        self.assertTrue(Supplier.objects.filter(pk=supplier.pk).exists())
        self.assertContains(response, 'Mark the supplier inactive instead')

    def test_non_staff_cannot_delete_supplier_or_product(self):
        supplier = Supplier.objects.create(name='Protected supplier')
        product = self.create_product(supplier)

        supplier_response = self.client.post(
            reverse('supplier_delete', kwargs={'pk': supplier.pk}),
        )
        product_response = self.client.post(
            reverse('product_delete', kwargs={'pk': product.pk}),
        )

        self.assertEqual(supplier_response.status_code, 403)
        self.assertEqual(product_response.status_code, 403)

    def test_supplier_filter_combines_with_existing_product_filters(self):
        supplier = Supplier.objects.create(name='Filtered supplier')
        other_supplier = Supplier.objects.create(name='Other supplier')
        category = Category.objects.create(name='Filter category')
        product = self.create_product(
            supplier,
            name='Filtered item',
            sku='FILTER-SUP-1',
            category=category,
        )
        self.create_product(
            other_supplier,
            name='Filtered other item',
            sku='FILTER-SUP-2',
        )

        response = self.client.get(reverse('product_list'), {
            'q': 'Filtered',
            'supplier': supplier.pk,
            'category': category.pk,
            'status': 'active',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['products']), [product])
        self.assertEqual(response.context['supplier_filter'], str(supplier.pk))

    def test_supplier_list_includes_annotated_product_count(self):
        supplier = Supplier.objects.create(name='Counted supplier')
        self.create_product(supplier, sku='COUNT-SUP-1')
        self.create_product(supplier, name='Second supplied product', sku='COUNT-SUP-2')

        response = self.client.get(reverse('supplier_list'))

        supplier_in_list = next(
            item
            for item in response.context['suppliers']
            if item.pk == supplier.pk
        )
        self.assertEqual(supplier_in_list.product_count, 2)

    def test_supplier_list_paginates_twenty_per_page(self):
        for index in range(21):
            Supplier.objects.create(name=f'Pagination supplier {index:02d}')

        first_page = self.client.get(reverse('supplier_list'))
        second_page = self.client.get(reverse('supplier_list'), {'page': 2})

        self.assertEqual(len(first_page.context['suppliers']), 20)
        self.assertEqual(len(second_page.context['suppliers']), 1)

    def test_dashboard_shows_top_suppliers_by_stock_value(self):
        supplier = Supplier.objects.create(name='Highest value supplier')
        self.create_product(
            supplier,
            name='Valuable product',
            sku='VALUE-SUP-1',
            quantity=10,
        )

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, supplier.name)
        self.assertEqual(response.context['top_suppliers'][0].stock_value, Decimal('120.00'))

    def test_supplier_detail_shows_products_and_stock_value(self):
        supplier = Supplier.objects.create(name='Detail supplier')
        self.create_product(supplier, name='Detail product', sku='DETAIL-SUP-1', quantity=3)

        response = self.client.get(
            reverse('supplier_detail', kwargs={'pk': supplier.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Detail product')
        self.assertEqual(response.context['stock_value'], Decimal('36.00'))

    def test_product_delete_control_is_staff_only(self):
        supplier = Supplier.objects.create(name='Action supplier')
        product = self.create_product(
            supplier,
            name='Action product',
            sku='ACTION-SUP-1',
        )

        self.assertNotContains(
            self.client.get(reverse('product_list')),
            reverse('product_delete', kwargs={'pk': product.pk}),
        )
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('product_list'))
        self.assertContains(
            response,
            reverse(
                'product_delete',
                kwargs={'pk': Product.objects.get(sku='ACTION-SUP-1').pk},
            ),
        )


class ProductPriceMigrationTests(TransactionTestCase):
    migrate_from = [('inventory', '0001_initial')]
    migrate_to = [('inventory', '0002_category_unit_product_details')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldProduct = old_apps.get_model('inventory', 'Product')
        OldProduct.objects.create(
            name='Legacy price product',
            sku='LEGACY-001',
            supplier_name='Legacy supplier',
            price=Decimal('42.75'),
            quantity=6,
            low_stock_threshold=2,
        )
        get_user_model().objects.create_superuser(
            username='migrationadmin',
            email='migrationadmin@example.com',
            password='A-strong-password-502!',
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.migrated_apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_price_is_preserved_and_piece_unit_assigned(self):
        ProductAtMigration = self.migrated_apps.get_model('inventory', 'Product')
        UnitAtMigration = self.migrated_apps.get_model('inventory', 'Unit')
        product = ProductAtMigration.objects.get(sku='LEGACY-001')

        self.assertEqual(product.selling_price, Decimal('42.75'))
        self.assertEqual(product.cost_price, Decimal('0'))
        self.assertEqual(product.unit.name, 'Piece')
        self.assertEqual(UnitAtMigration.objects.filter(name='Piece').count(), 1)


class StockMovementDataMigrationTests(TransactionTestCase):
    migrate_from = [('inventory', '0003_add_pair_unit')]
    migrate_to = [('inventory', '0004_stockmovement')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldProduct = old_apps.get_model('inventory', 'Product')
        creator = get_user_model().objects.create_superuser(
            username='openingadmin',
            email='openingadmin@example.com',
            password='A-strong-password-502!',
        )
        OldProduct.objects.create(
            name='Existing stocked product',
            sku='MIGRATE-001',
            supplier_name='',
            selling_price=Decimal('5.00'),
            cost_price=Decimal('2.00'),
            quantity=7,
            low_stock_threshold=1,
        )
        OldProduct.objects.create(
            name='Existing zero-stock product',
            sku='MIGRATE-002',
            supplier_name='',
            selling_price=Decimal('5.00'),
            cost_price=Decimal('2.00'),
            quantity=0,
            low_stock_threshold=1,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.migrated_apps = executor.loader.project_state(self.migrate_to).apps
        self.creator_id = creator.pk

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_products_receive_opening_stock_snapshots(self):
        Movement = self.migrated_apps.get_model('inventory', 'StockMovement')
        ProductAtMigration = self.migrated_apps.get_model('inventory', 'Product')

        self.assertEqual(Movement.objects.count(), 2)
        movement = Movement.objects.get(product__sku='MIGRATE-001')
        self.assertEqual(movement.created_by_id, self.creator_id)
        self.assertEqual(movement.movement_type, 'IN')
        self.assertEqual(movement.quantity, 7)
        self.assertEqual(movement.quantity_change, 7)
        self.assertEqual((movement.quantity_before, movement.quantity_after), (0, 7))
        zero_movement = Movement.objects.get(product__sku='MIGRATE-002')
        self.assertEqual(zero_movement.quantity, 0)
        self.assertEqual(zero_movement.quantity_change, 0)
        self.assertEqual(
            ProductAtMigration.objects.get(sku='MIGRATE-002').quantity,
            zero_movement.quantity_after,
        )


class SupplierDataMigrationTests(TransactionTestCase):
    migrate_from = [('inventory', '0004_stockmovement')]
    migrate_to = [('inventory', '0006_remove_product_supplier_name')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldProduct = old_apps.get_model('inventory', 'Product')
        for sku, supplier_name in (
            ('VENDOR-001', 'Legacy vendor'),
            ('VENDOR-002', 'Legacy vendor'),
            ('VENDOR-003', ''),
        ):
            OldProduct.objects.create(
                name=f'Legacy product {sku}',
                sku=sku,
                supplier_name=supplier_name,
                selling_price=Decimal('5.00'),
                quantity=4,
                low_stock_threshold=1,
            )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.migrated_apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_supplier_names_are_created_and_products_linked_without_data_loss(self):
        SupplierAtMigration = self.migrated_apps.get_model('inventory', 'Supplier')
        ProductAtMigration = self.migrated_apps.get_model('inventory', 'Product')

        supplier = SupplierAtMigration.objects.get(name='Legacy vendor')
        self.assertEqual(SupplierAtMigration.objects.count(), 1)
        self.assertEqual(
            ProductAtMigration.objects.filter(supplier_id=supplier.pk).count(),
            2,
        )
        self.assertIsNone(
            ProductAtMigration.objects.get(sku='VENDOR-003').supplier_id,
        )
        self.assertEqual(
            list(
                ProductAtMigration.objects.filter(supplier_id=supplier.pk)
                .values_list('quantity', flat=True)
            ),
            [4, 4],
        )
