from django.db import migrations


def add_pair_unit(apps, schema_editor):
    Unit = apps.get_model('inventory', 'Unit')
    Unit.objects.using(schema_editor.connection.alias).get_or_create(
        name='Pair',
        defaults={'short_code': 'pair'},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_category_unit_product_details'),
    ]

    operations = [
        migrations.RunPython(add_pair_unit, migrations.RunPython.noop),
    ]
