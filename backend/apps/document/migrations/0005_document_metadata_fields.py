# Generated manually

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('document', '0004_smartchunk_content_norm'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='year',
            field=models.IntegerField(blank=True, help_text='Año del documento', null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='region',
            field=models.CharField(blank=True, help_text='Región del documento', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='document',
            name='topics',
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.TextField(),
                blank=True,
                default=list,
                help_text='Temas o palabras clave del documento',
                size=None
            ),
        ),
        migrations.AddField(
            model_name='document',
            name='source',
            field=models.CharField(blank=True, help_text='Fuente del documento', max_length=255, null=True),
        ),
    ]

