from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.core.validators import RegexValidator
from django.db.models import Q
from .models import Category, Product, StockMovement, Supplier


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'description')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Electronics'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Optional notes about this category',
            }),
        }


class SupplierForm(forms.ModelForm):
    phone = forms.CharField(
        required=False,
        max_length=30,
        validators=[
            RegexValidator(
                regex=r'^[0-9+\-]*$',
                message='Use digits, plus signs, or hyphens only.',
            ),
        ],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+1-555-0100',
        }),
    )

    class Meta:
        model = Supplier
        fields = (
            'name',
            'contact_person',
            'phone',
            'email',
            'address',
            'city',
            'payment_terms',
            'notes',
            'is_active',
        )
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Supplier name'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'payment_terms': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Invalid username/email or password. Please try again.',
    }
    username = forms.CharField(
        label='Username or email',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'username',
            'autofocus': True,
            'placeholder': 'Enter your username or email',
        }),
    )
    password = forms.CharField(
        label='Password',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'current-password',
            'placeholder': 'Enter your password',
        }),
    )

    def clean_username(self):
        username = self.cleaned_data['username']
        if '@' not in username:
            return username

        users = get_user_model().objects.filter(email__iexact=username)
        user = users.first()
        if user is not None and not users.exclude(pk=user.pk).exists():
            return user.get_username()
        return username


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'autocomplete': 'email',
            'placeholder': 'you@example.com',
        }),
    )

    class Meta(UserCreationForm.Meta):
        fields = ('username', 'email')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'username',
                'placeholder': 'Choose a username',
            }),
        }

    def clean_email(self):
        email = self.cleaned_data['email']
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
            'placeholder': 'Create a password',
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
            'placeholder': 'Confirm your password',
        })


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'email',
            'placeholder': 'you@example.com',
        })


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
            'placeholder': 'Enter a new password',
        })
        self.fields['new_password2'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
            'placeholder': 'Confirm your new password',
        })


class ProductForm(forms.ModelForm):
    quantity = forms.IntegerField(
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
        }),
    )

    class Meta:
        model = Product
        fields = [
            'name',
            'sku',
            'category',
            'unit',
            'supplier',
            'description',
            'image',
            'cost_price',
            'selling_price',
            'quantity',
            'low_stock_threshold',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product name'}),
            'sku': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Leave blank to generate automatically',
            }),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'unit': forms.Select(attrs={'class': 'form-control'}),
            'supplier': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Optional product details',
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control image-upload',
                'accept': 'image/*',
            }),
            'cost_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
            }),
            'selling_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
            }),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'low_stock_threshold': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields.pop('quantity')
        self.fields['sku'].required = False
        self.fields['sku'].help_text = 'Leave blank to generate a category-based SKU.'
        self.fields['category'].queryset = self.fields['category'].queryset.order_by('name')
        self.fields['unit'].queryset = self.fields['unit'].queryset.order_by('name')
        active_suppliers = Supplier.objects.filter(is_active=True)
        if self.instance.pk and self.instance.supplier_id:
            active_suppliers = Supplier.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.supplier_id),
            )
        self.fields['supplier'].queryset = active_suppliers.order_by('name')


class StockProductSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        if value is not None and getattr(value, 'instance', None) is not None:
            option['attrs'].update({
                'data-current-stock': value.instance.quantity,
                'data-current-unit': (
                    value.instance.unit.short_code
                    if value.instance.unit_id
                    else 'units'
                ),
            })
        return option


class StockMovementForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        widget=StockProductSelect(attrs={'class': 'form-control', 'data-stock-product': ''}),
    )
    quantity = forms.IntegerField(
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'data-movement-quantity': '',
        }),
    )
    reason = forms.ChoiceField(
        choices=(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Optional details',
        }),
    )
    reference = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. invoice or PO number',
        }),
    )

    def __init__(self, *args, movement_type, **kwargs):
        super().__init__(*args, **kwargs)
        self.movement_type = movement_type
        self.fields['product'].queryset = Product.objects.select_related(
            'unit',
        ).order_by('name')
        self.fields['product'].label_from_instance = (
            lambda product: f'{product.name} ({product.sku})'
        )
        self.fields['reason'].choices = [
            ('', 'Select a reason'),
            *(
                (reason, reason)
                for reason in StockMovement.MOVEMENT_REASONS[movement_type]
            ),
        ]
        if movement_type == StockMovement.MovementType.ADJUST:
            self.fields['quantity'].label = 'Counted quantity'
            self.fields['quantity'].help_text = 'Enter the new counted stock quantity.'
        else:
            self.fields['quantity'].label = 'Quantity'
            self.fields['quantity'].min_value = 1
            self.fields['quantity'].widget.attrs['min'] = '1'
            self.fields['quantity'].help_text = 'Enter the quantity to move.'

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        if (
            self.movement_type != StockMovement.MovementType.ADJUST
            and quantity == 0
        ):
            raise forms.ValidationError('Quantity must be greater than zero.')
        return quantity