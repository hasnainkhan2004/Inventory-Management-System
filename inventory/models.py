from django.core.validators import MinValueValidator
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Supplier(models.Model):
    class PaymentTerms(models.TextChoices):
        CASH = 'Cash', 'Cash'
        DAYS_7 = '7 days', '7 days'
        DAYS_15 = '15 days', '15 days'
        DAYS_30 = '30 days', '30 days'

    name = models.CharField(max_length=100, unique=True)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    payment_terms = models.CharField(
        max_length=10,
        choices=PaymentTerms.choices,
        default=PaymentTerms.CASH,
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Unit(models.Model):
    name = models.CharField(max_length=50)
    short_code = models.CharField(max_length=10)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=100)
    sku = models.CharField(max_length=50, unique=True, blank=True)
    category = models.ForeignKey(
        Category,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='products',
    )
    unit = models.ForeignKey(
        Unit,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='products',
    )
    supplier = models.ForeignKey(
        Supplier,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='products',
    )
    image = models.ImageField(upload_to='products/', blank=True)
    description = models.TextField(blank=True)
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    quantity = models.IntegerField(default=0)
    low_stock_threshold = models.IntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cost_price__gte=0),
                name='product_cost_price_nonnegative',
            ),
        ]

    def __str__(self):
        return self.name

    def is_low_stock(self):
        return self.quantity < self.low_stock_threshold

    def save(self, *args, **kwargs):
        if not self.sku or not self.sku.strip():
            category_name = self.category.name if self.category_id else ''
            prefix = ''.join(
                character.upper()
                for character in category_name
                if character.isascii() and character.isalpha()
            )[:3] or 'GEN'
            existing_skus = Product.objects.filter(
                sku__startswith=f'{prefix}-',
            ).exclude(pk=self.pk).values_list('sku', flat=True)
            sequence = max(
                (
                    int(existing_sku[len(prefix) + 1:])
                    for existing_sku in existing_skus
                    if existing_sku[len(prefix) + 1:].isdigit()
                ),
                default=0,
            ) + 1
            self.sku = f'{prefix}-{sequence:04d}'
            while Product.objects.filter(sku=self.sku).exclude(pk=self.pk).exists():
                sequence += 1
                self.sku = f'{prefix}-{sequence:04d}'
        super().save(*args, **kwargs)


class ImmutableStockMovementQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Stock movements are immutable.')

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError('Stock movements are immutable.')

    def delete(self):
        raise ValidationError('Stock movements cannot be deleted.')


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        IN = 'IN', 'Stock In'
        OUT = 'OUT', 'Stock Out'
        ADJUST = 'ADJUST', 'Adjustment'

    MOVEMENT_REASONS = {
        MovementType.IN: (
            'Purchase',
            'Customer return',
            'Opening stock',
            'Other',
        ),
        MovementType.OUT: (
            'Sale',
            'Damaged',
            'Expired',
            'Lost',
            'Internal use',
            'Other',
        ),
        MovementType.ADJUST: (
            'Stock count correction',
            'Other',
        ),
    }
    REASON_CHOICES = tuple(
        (reason, reason)
        for reason in dict.fromkeys(
            reason
            for reasons in MOVEMENT_REASONS.values()
            for reason in reasons
        )
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='stock_movements',
    )
    movement_type = models.CharField(max_length=8, choices=MovementType.choices)
    quantity = models.PositiveIntegerField()
    quantity_change = models.IntegerField()
    quantity_before = models.PositiveIntegerField()
    quantity_after = models.PositiveIntegerField()
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    note = models.TextField(blank=True)
    reference = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='stock_movements',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableStockMovementQuerySet.as_manager()

    class Meta:
        ordering = ('-created_at', '-pk')
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(quantity__gt=0)
                    | models.Q(reason='Opening stock')
                ),
                name='stock_movement_quantity_positive',
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(quantity_change=0)
                    | models.Q(reason='Opening stock')
                ),
                name='stock_movement_change_nonzero',
            ),
        ]

    def __str__(self):
        return f'{self.get_movement_type_display()} · {self.product}'

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Stock movements are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Stock movements cannot be deleted.')