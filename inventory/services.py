from django.db import transaction

from .models import Product, StockMovement


class StockMovementError(ValueError):
    pass


@transaction.atomic
def apply_stock_movement(
    product,
    movement_type,
    quantity,
    reason,
    user,
    note='',
    reference='',
):
    if movement_type not in StockMovement.MovementType.values:
        raise StockMovementError('Choose a valid stock movement type.')

    if reason not in StockMovement.MOVEMENT_REASONS[movement_type]:
        raise StockMovementError('Choose a valid reason for this stock movement.')
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise StockMovementError('Quantity must be a whole number.')

    locked_product = Product.objects.select_for_update().get(pk=product.pk)
    quantity_before = locked_product.quantity

    if movement_type == StockMovement.MovementType.ADJUST:
        if quantity < 0:
            raise StockMovementError('Counted stock cannot be negative.')
        quantity_change = quantity - quantity_before
        if quantity_change == 0:
            raise StockMovementError('The counted stock matches the current quantity.')
        movement_quantity = abs(quantity_change)
    else:
        if quantity <= 0:
            raise StockMovementError('Quantity must be greater than zero.')
        movement_quantity = quantity
        quantity_change = (
            quantity
            if movement_type == StockMovement.MovementType.IN
            else -quantity
        )

    quantity_after = quantity_before + quantity_change
    if quantity_after < 0:
        raise StockMovementError(
            f'Cannot remove {movement_quantity} units; only '
            f'{quantity_before} are available.'
        )

    locked_product.quantity = quantity_after
    locked_product.save(update_fields=('quantity', 'updated_at'))
    return StockMovement.objects.create(
        product=locked_product,
        movement_type=movement_type,
        quantity=movement_quantity,
        quantity_change=quantity_change,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        reason=reason,
        note=note,
        reference=reference,
        created_by=user,
    )
